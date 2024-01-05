#!/usr/bin/env python3

import argparse
import itertools
import json
import os
import subprocess
import sys
from typing import Iterable, List, Optional, Sequence, Set, Tuple

debug_enabled = os.getenv("DEVEL_DIR_DEBUG", None) is not None


def debug(*args, **kwargs):
    if debug_enabled:
        args = list(args)
        args[0] = "\x1b[1;33m" + str(args[0])
        args[-1] = str(args[-1]) + "\x1b[0m"
        print(*args, file=sys.stderr, **kwargs)


def info_message(*args, **kwargs):
    print(*args, **kwargs, file=sys.stderr)


def warning(*args, **kwargs):
    print(*args, **kwargs, file=sys.stderr)


def die(*args, **kwargs):
    print(*args, **kwargs, file=sys.stderr)
    print("Run command again with DEVEL_DIR_DEBUG env var set to see debug output", file=sys.stderr)
    sys.exit(1)


def output_result(r):
    print(r, file=sys.stdout)
    sys.exit()


def strip_end(text, suffix):
    if not text.endswith(suffix):
        return text
    return text[:len(text)-len(suffix)]


def safe_getcwd():
    # os.getcwd fails when used in a directory that has been deleted:
    try:
        return os.getcwd()
    except FileNotFoundError:
        return "/"


# A class that lazily computes the real path
class Directory(object):
    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        if not self.path.endswith("/"):
            self.path += "/"
        self.__real_path: Optional[str] = None

    @property
    def real_path(self) -> str:
        if self.__real_path is None:
            self.__real_path = os.path.realpath(self.path)
            assert self.__real_path.startswith("/"), self.__real_path
            if not self.__real_path.endswith("/"):
                self.__real_path += "/"
        assert isinstance(self.__real_path, str)
        return self.__real_path

    def is_subdirectory_of(self, other: "Directory"):
        assert isinstance(other, Directory)
        if self.path.startswith(other.path) or self.real_path.startswith(other.path):
            return True
        if self.path.startswith(other.real_path) or self.real_path.startswith(other.real_path):
            return True
        return False

    def try_replace_prefix(self, prefix: "Directory", replacement: str) -> Optional[str]:
        for src, dest in itertools.product((self.path, self.real_path), (prefix.path, prefix.real_path)):
            assert src.endswith("/"), src
            assert dest.endswith("/"), dest
            if src.startswith(dest):
                return src.replace(dest, replacement)
        return None

    def replace_prefix(self, prefix: "Directory", replacement: str) -> str:
        result = self.try_replace_prefix(prefix, replacement)
        if result is None:
            die("Could not replace prefix", prefix, "with", replacement, "in", self)
        return result

    def __repr__(self):
        return self.path


class DirMapping(object):
    def __init__(self, value: dict, default_build_suffixes: "list[str]"):
        self.source = Directory(os.path.expandvars(value["source"]))
        build_json = value["build"]
        self.build_dirs = []
        if build_json:
            if not isinstance(build_json, list):
                build_json = [build_json]
            self.build_dirs = [Directory(os.path.expandvars(s)) for s in build_json]
        self.build_suffixes = value.get("build-suffixes", default_build_suffixes)  # type: List[str]
        self.basename: "Optional[list[str]]" = value.get("basename", None)

    def __repr__(self):
        return repr(self.source) + " -> " + repr(self.build_dirs)


class DevelDirs(object):
    def __init__(self):
        # config_dir = os.getenv("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
        config_dir = os.path.expanduser("~/.config")
        config_file = os.path.join(config_dir, "devel_dirs.json")
        try:
            self.config_data = dict()
            with open(config_file, 'r') as f:
                self.config_data = json.load(f)  # type: dict
        except FileNotFoundError:
            die("Could not find config file", config_file)
        except ValueError as e:
            die("Could not parse JSON data from " + config_file + ":", e)

        self.default_suffixes = self.config_data.get("build-suffixes", [])  # type: List[str]
        dirs_map = map(lambda x: DirMapping(x, self.default_suffixes), self.config_data["directories"])
        self.directories = list(dirs_map)  # type: List[DirMapping]
        self.ignored_dirs = self.config_data.get("ignored_directories", [])  # type: List[str]
        debug("directories:", self.directories)

        # cache_dir = os.getenv("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))
        cache_dir = os.path.expanduser("~/.cache")
        self.cache_file = os.path.join(cache_dir, "devel-dirs.cache")
        self.__cache_data = None

    @property
    def cache_data(self) -> dict:
        if self.__cache_data is None:
            try:
                # Load the cache file:
                with open(self.cache_file, 'r') as f:
                    self.__cache_data = json.load(f)
                    # debug("Cache data:", self.__cache_data)
            except (IOError, json.decoder.JSONDecodeError):
                self.__cache_data = {}
                warning('Cache data was invalid, assuming empty!')
        assert isinstance(self.__cache_data, dict)
        return self.__cache_data

    @property
    def overrides(self) -> Iterable[DirMapping]:
        # we only iterate over this once, make it a lazy property
        return map(lambda x: DirMapping(x, self.default_suffixes), self.config_data.get("overrides", []))

    # noinspection PyBroadException
    @staticmethod
    def prompt_from_choices(*msg, choices: Sequence[str]) -> Directory:
        assert len(choices) > 0
        if len(choices) == 1:
            return Directory(choices[0])
        choices = sorted(choices)
        info_message(*msg)
        for i, s in enumerate(choices):
            info_message('  [' + str(i + 1) + ']', s)
        chosen = "<none>"
        try:
            # input prompts on stdout, but we read stdout -> print to stderr instead
            info_message('Which one did you mean? ', end='')
            chosen = input()
            if int(chosen) < 1 or int(chosen) > len(choices):
                raise RuntimeError("Out of range")
            return Directory(choices[int(chosen) - 1])
        except:
            die("Invalid choice: ", chosen)

    def get_dir_for_repo(self, repo_name: str) -> Optional[Directory]:
        debug("Finding repo", repo_name)
        if repo_name not in self.cache_data:
            warning("Could not find repository", repo_name)
            return None
        dirs = self.cache_data[repo_name]
        if len(dirs) == 0:
            die("Corrupted cache file:", repo_name, "is empty!")
        return self.prompt_from_choices("Multiple source directories found for name", repo_name, choices=dirs)

    @staticmethod
    def _get_build_dir_candidates(relative_path: str, builddir: Directory, suffixes: List[str]) -> Tuple[set, set]:
        candidates = set()
        root_candidates = set()
        assert not relative_path.startswith("/")
        debug("relative:", relative_path)
        parts = list(filter(None, relative_path.split("/")))
        if not parts:
            parts = ["/"]
        debug("parts:", parts)
        for suffix in suffixes + [""]:
            for i, name in enumerate(parts):
                new_parts = list(parts)
                name = name.rstrip("/")
                new_parts[i] = name + suffix
                directory = os.path.join(builddir.path, *new_parts)
                debug("checking", directory, end=" ")
                if os.path.isdir(directory):
                    debug("-> exists")
                    candidates.add(directory)
                else:
                    debug("-> not a directory")
                    # try if this is a build directory root
                    possible_root = os.path.join(builddir.path, *new_parts[:i + 1])
                    if os.path.isdir(possible_root):
                        debug("   but found potential root dir:", possible_root)
                        root_candidates.add(possible_root)
        return candidates, root_candidates

    def _try_build_dir_mapping(self, mapping: DirMapping, path: Directory):
        relative_path = mapping.basename if mapping.basename else path.try_replace_prefix(mapping.source, "")
        if relative_path is None:
            return
        if not mapping.build_dirs:
            die("No build directory defined for source root", mapping.source)
        candidates = set()
        build_root_candidates = set()
        for build_dir in mapping.build_dirs:
            # Try to find any suffixed dir that exists (slow but we don't need to be efficient)
            full, root_path = self._get_build_dir_candidates(relative_path, build_dir, mapping.build_suffixes)
            candidates = candidates.union(full)
            build_root_candidates = build_root_candidates.union(root_path)
        debug("candidates", candidates, "root", build_root_candidates)
        if candidates:
            result = self.prompt_from_choices("Multiple build directories found", choices=list(candidates))
            output_result(result)
        elif build_root_candidates:
            result = self.prompt_from_choices("Multiple build root directories found",
                                              choices=list(build_root_candidates))
            output_result(result)
        else:
            die("Could not find build directory for", path)

    def get_build_dir(self, repository_name: Optional[str]):
        # noinspection PyUnresolvedReferences
        if repository_name:
            path = self.get_dir_for_repo(repository_name)
            if not path:
                die("Cannot find repository for", repository_name)
        else:
            path = Directory(os.path.realpath(safe_getcwd()))

        debug("Finding build dir for", path)
        # check if we are already in a build dir:
        for mapping in self.directories:
            if any(path.is_subdirectory_of(build_dir) for build_dir in mapping.build_dirs):
                sys.stderr.write("Already in build dir.\n")
                output_result(path)

        # check whether a custom mapping exists:
        for override in self.overrides:
            debug("checking override", override)
            if not path.is_subdirectory_of(override.source):
                debug("skipping", override.source, "since", path, "is not a subdirectory")
                continue
            debug("Found potential build dir mapping:", override)
            self._try_build_dir_mapping(override, path)

        for mapping in self.directories:
            if not path.is_subdirectory_of(mapping.source):
                debug("skipping", mapping.source, "since", path, "is not a subdirectory")
                continue
            self._try_build_dir_mapping(mapping, path)

        # final fallback: not in build dir before -> change to build dir root
        output_result(self.directories[0].build_dirs[0].path)

    def get_source_dir(self, repository_name: Optional[str]):
        if repository_name:
            cached_source_dir = self.get_dir_for_repo(repository_name)
            if cached_source_dir:
                self._check_and_output_source_dir_result(cached_source_dir)
            else:
                # Try iterating over the subdirectories of all source roots
                for mapping in itertools.chain(self.directories, self.overrides):
                    candidate = os.path.join(mapping.source.path, repository_name)
                    debug("trying", candidate)
                    if os.path.isdir(candidate):
                        warning("Source directory for", repository_name, "guessed as", candidate)
                        info_message("Consider running `", sys.argv[0], " update-cache ", mapping.source.path, "`",
                                     sep="")
                        info_message("Do you want to do this now? [y/N] ", end="")
                        if input().lower()[:1] == "y":
                            self._update_cache(mapping.source.path, 2, pretend=False)
                        output_result(candidate)
                die("Cannot find repository for", repository_name)

        # find the matching source dir for CWD
        cwd = Directory(safe_getcwd())

        # check if we are already in a source dir:
        for mapping in self.directories:
            # build directories can be below the source root (e.g src=~/cheri/llvm, build=~/cheri/build/llvm)
            in_build_dir = any(cwd.is_subdirectory_of(build_dir) for build_dir in mapping.build_dirs)
            if cwd.is_subdirectory_of(mapping.source) and not in_build_dir:
                sys.stderr.write("Already in source dir.\n")
                output_result(cwd)

        candidates = set()
        found_match = False
        # check whether a custom mapping exists:
        for mapping in list(self.overrides) + self.directories:
            result = self._try_as_source_directory(cwd, mapping)
            debug("candidates for mapping '", mapping, "': ",  result, sep="")
            if result is not None:
                found_match = True
                candidates = candidates.union(result)
        debug("final candidates:", candidates)
        if found_match:
            if candidates:
                result = self.prompt_from_choices("Multiple source directories found", choices=list(candidates))
                self._check_and_output_source_dir_result(result)
            else:
                die("Could not find source directory for", cwd)
        # FIXME: this is currently broken
        # final fallback: not in source dir before -> change to default source dir
        output_result(self.directories[0].source)

    def _check_and_output_source_dir_result(self, result: Directory):
        if not os.path.isdir(result.path):
            warning("Chosen project no longer exists: ", result)
            info_message("Consider running `", sys.argv[0], " cleanup-cache ", sep="")
            info_message("Do you want to do this now? [y/N] ", end="")
            if input().lower()[:1] == "y":
                self._cleanup_cache()
        output_result(result)

    @staticmethod
    def _try_as_source_directory(path, mapping: DirMapping) -> Optional[Set]:
        # XXXAR: this code is horrible....
        candidates = set()
        for build_dir in mapping.build_dirs:
            # check if prefix matches
            relative_path = path.try_replace_prefix(build_dir, "")
            if relative_path is None:
                continue
            debug("Found", path, "in", mapping)
            assert mapping.source

            # see if there any suffixes that we need to remove
            default_result = mapping.source.path + relative_path
            if os.path.isdir(default_result):
                debug("Found source candidate", default_result)
                candidates.add(default_result)
            if not mapping.build_suffixes:
                continue

            # Try to find any suffixed dir that exists (slow but we don't need to be efficient)
            assert not relative_path.startswith("/")
            debug("relative:", relative_path)
            parts = list(filter(None, relative_path.split("/")))
            debug("parts:", parts)
            for i, name in enumerate(parts):
                debug("trying to remove suffix from", name)
                name = name.rstrip("/")
                for suffix in mapping.build_suffixes + [""]:
                    if not name.endswith(suffix):
                        continue
                    new_parts = list(parts)
                    new_parts[i] = strip_end(name, suffix)
                    directory = os.path.join(mapping.source.path, *new_parts)
                    debug("checking if", directory, "exists")
                    if os.path.isdir(directory):
                        debug("Adding", directory)
                        candidates.add(directory)
        return candidates

    def update_cache(self, args: argparse.Namespace):
        info_message('saving to', self.cache_file)
        # noinspection PyUnresolvedReferences
        if args.path is None:
            debug("Updating all dirs")
            paths = [str(mapping.source.path) for mapping in self.directories]
        else:
            # noinspection PyUnresolvedReferences
            paths = [args.path]
        # noinspection PyUnresolvedReferences
        if args.depth is None:
            level = input("How many levels below the root would you like to search for projects? [Default=2] ")
            try:
                depth = int(level) if level else 2
                if depth < 1:
                    die("Invalid depth:", level)
            except ValueError:
                die("Could not convert", level, "to an integer value")
                return
        else:
            # noinspection PyUnresolvedReferences
            depth = args.depth

        if not paths:
            die("Could not find any paths to update. Is your ~/.config/devel_dirs.json valid?")
        for path in paths:
            self._update_cache(path, depth, args.pretend)

    def _update_cache(self, path: str, depth: int, pretend: bool):
        info_message("Checking", path, "for projects")
        # TODO: use os.walk()? Slower but more portable
        # Also handle .gitrepo files for git-subrepo (libunwind/libcxx, etc)
        dotgit_dirs_list = subprocess.check_output([
            'find', path, '-maxdepth', str(depth),
            '(', '-name', '.git', '-o', '-name', '.gitrepo', ')', '-print0']).decode('utf-8').split('\0')
        # -printf does not work on FreeBSD
        # we need to go up one dir from .git and use the absolute path
        dirs_list = [os.path.realpath(os.path.dirname(p)) for p in dotgit_dirs_list if p]
        info_message(list(dirs_list))
        for d in dirs_list:
            if any(d.startswith(ignored_root) for ignored_root in self.ignored_dirs):
                info_message('Not adding repo', d, 'since it is below an ignored dir')
                continue
            repo_name = os.path.basename(d)
            if repo_name not in self.cache_data:
                info_message('Adding repo', d, 'in', repo_name)
                self.cache_data[repo_name] = [d]
            elif d not in self.cache_data[repo_name]:
                info_message('Adding', d, 'as another repo for', repo_name)
                self.cache_data[repo_name].append(d)
            else:
                info_message('Repo', d, 'already exists in cache')
        # info_message(json.dumps(self.cache_data))
        if pretend:
            json.dump(self.cache_data, sys.stdout, indent=4)
        else:
            os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
            with open(self.cache_file, 'w+') as cacheFile:
                json.dump(self.cache_data, cacheFile, indent=4)
                cacheFile.flush()

    def cache_lookup(self, args: argparse.Namespace):
        # return all possibilities when no arg passed, otherwise filter
        candidates = []
        # noinspection PyUnresolvedReferences
        if len(args.name_prefix) > 0:
            for k in self.cache_data.keys():
                # noinspection PyUnresolvedReferences
                if k.startswith(args.name_prefix):
                    candidates.append(k)
        else:
            # just return all of them
            candidates = self.cache_data.keys()
        output_result(" ".join(candidates))

    def cleanup_cache(self, args: argparse.Namespace):
        # noinspection PyUnresolvedReferences
        self._cleanup_cache(pretend=args.pretend)

    def _cleanup_cache(self, pretend: bool = False):
        # make a copy since we are modifying while iterating
        cache_data_copy = dict(self.cache_data)
        if len(self.cache_data) == 0:
            info_message("Cache is empty")
            sys.exit(0)
        changed = False
        debug("Cleaning up cache. Ignored dirs are", self.ignored_dirs)
        for key, values in self.cache_data.items():
            # info_message("key =", key, "values=", values)
            for path in values:
                is_ignored = False
                debug("Checking", path)
                for ignored in self.ignored_dirs:
                    assert ignored.endswith("/")
                    if os.path.realpath(path).startswith(ignored):
                        debug(path, "is below ignored dir", ignored)
                        is_ignored = True
                        break
                if not os.path.isdir(path) or is_ignored:
                    reason = "is below ignored directory" if is_ignored else "no longer exists"
                    changed = True
                    if len(values) > 1:
                        values.remove(path)
                        cache_data_copy[key] = values
                        info_message("Removed", path, "from cache for", key, "as it", reason)
                        info_message("   remaining paths are:", values)
                    else:
                        del cache_data_copy[key]
                        info_message("Removed ", key, " (", path, ") from cache as it", reason, sep='')

        if not changed:
            info_message("All entries in cache are valid.")
        if not pretend:
            with open(self.cache_file, 'w+') as f:
                json.dump(cache_data_copy, f, indent=4)
                f.flush()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--debug', action="store_true", help='Don\'t actually cleanup the cache, only print actions')
    subparsers = parser.add_subparsers(dest='subparser_name', help='sub-command help', required=True)
    parser_source = subparsers.add_parser('source', help='Get path to source dir')
    parser_source.add_argument('repository_name', default='', nargs='?', help='The name of the repository')
    parser_source.set_defaults(func=lambda args: devel_dirs.get_source_dir(args.repository_name))

    parser_build = subparsers.add_parser('build', help='Get path to build dir')
    parser_build.add_argument('repository_name', default='', nargs='?', help='The name of the repository')
    parser_build.set_defaults(func=lambda args: devel_dirs.get_build_dir(args.repository_name))

    parser_cache_lookup = subparsers.add_parser('cache-lookup',
                                                help='Get all repositories that start with given prefix')
    parser_cache_lookup.add_argument('name_prefix', help='The first few characters of the name')
    parser_cache_lookup.set_defaults(func=lambda args: devel_dirs.cache_lookup(args))

    parser_update_cache = subparsers.add_parser('update-cache', help='Update the source dirs cache')
    parser_update_cache.add_argument('path', nargs='?', default=None,
                                     help='The path where repositories are searched for')
    parser_update_cache.add_argument('depth', nargs='?', default=None, type=int,
                                     help='The search depth for finding repositories')
    parser_update_cache.add_argument('--pretend', '-p', action="store_true",
                                     help='Don\'t actually cleanup the cache, only print actions')
    parser_update_cache.set_defaults(func=lambda args: devel_dirs.update_cache(args))

    parser_cleanup_cache = subparsers.add_parser('cleanup-cache', help='Update the source dirs cache')
    parser_cleanup_cache.add_argument('--pretend', '-p', action="store_true",
                                      help='Don\'t actually cleanup the cache, only print actions')
    parser_cleanup_cache.set_defaults(func=lambda args: devel_dirs.cleanup_cache(args))

    # parse the args and call whatever function was selected
    parsed_args = parser.parse_args()
    devel_dirs = DevelDirs()
    if parsed_args.debug:
        debug_enabled = True
    parsed_args.func(parsed_args)
