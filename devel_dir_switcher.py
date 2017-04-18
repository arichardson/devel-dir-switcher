#!/usr/bin/env python3

import json
import sys
import os
import subprocess
import argparse
import itertools
from typing import Optional, List, Iterable, Sequence, Set, Tuple


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


# A class that lazily computes the real path
class Directory(object):
    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        if not self.path.endswith("/"):
            self.path += "/"
        self.__real_path = None  # type: str

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
    def __init__(self, value: dict):
        self.source = Directory(os.path.expandvars(value["source"]))
        build_json = value["build"]
        self.build_dirs = []
        if build_json:
            if not isinstance(build_json, list):
                build_json = [build_json]
            self.build_dirs = [Directory(os.path.expandvars(s)) for s in build_json]
        self.build_suffixes = value.get("build-suffixes", [])  # type: List[str]

    def __repr__(self):
        return repr(self.source) + " -> " + repr(self.build_dirs)


class DevelDirs(object):
    def __init__(self):
        config_file = os.path.join(os.getenv("XDG_CACHE_HOME", os.path.expanduser("~/.config")), "devel_dirs.json")
        self.config_data = dict()
        with open(config_file, 'r') as f:
            self.config_data = json.load(f)  # type: dict

        self.directories = list(map(DirMapping, self.config_data["directories"]))  # type: List[DirMapping]
        debug("directories:", self.directories)

        cacheDir = os.getenv("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))
        self.cache_file = os.path.join(cacheDir, "devel-dirs.cache")
        self.__cache_data = None

    @property
    def cache_data(self) -> dict:
        if self.__cache_data is None:
            try:
                # Load the cache file:
                with open(self.cache_file, 'r') as f:
                    self.__cache_data = json.load(f)
                    # debug("Cache data:", self.__cache_data)
            except IOError:
                self.__cache_data = {}
                warning('Cache data was invalid, assuming empty!')
        assert isinstance(self.__cache_data, dict)
        return self.__cache_data

    @property
    def overrides(self) -> Iterable[DirMapping]:
        # we only iterate over this once, make it a lazy property
        return map(DirMapping, self.config_data.get("overrides", []))

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
                debug("checking", directory, end="")
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
        relative_path = path.try_replace_prefix(mapping.source, "")
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
            path = Directory(os.path.realpath(os.getcwd()))

        # check if we are already in a build dir:
        for mapping in self.directories:
            if any(path.is_subdirectory_of(build_dir) for build_dir in mapping.build_dirs):
                sys.stderr.write("Already in build dir.\n")
                output_result(path)

        # check whether a custom mapping exists:
        for override in self.overrides:
            debug("checking override", override)
            self._try_build_dir_mapping(override, path)

        for mapping in self.directories:
            self._try_build_dir_mapping(mapping, path)


        # final fallback: not in build dir before -> change to build dir root
        output_result(self.directories[0].build_dirs[0].path)

    def get_source_dir(self, repository_name: Optional[str]):
        if repository_name:
            cachedSourceDir = self.get_dir_for_repo(repository_name)
            if cachedSourceDir:
                output_result(cachedSourceDir)
            else:
                # Try iterating over the subdirectories of all source roots
                for mapping in self.directories:
                    candidate = os.path.join(mapping.source.path, repository_name)
                    if os.path.isdir(candidate):
                        warning("Source directory for", repository_name, "guessed as", candidate)
                        info_message("Consider running `", sys.argv[0], " update-cache ", mapping.source.path, "`",
                                     sep="")
                        output_result(candidate)
                die("Cannot find repository for", repository_name)

        # find the matching source dir for CWD
        cwd = Directory(os.getcwd())

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
                output_result(result)
            else:
                die("Could not find source directory for", cwd)
        # FIXME: this is currently broken
        # final fallback: not in source dir before -> change to default source dir
        output_result(self.directories[0].source)

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
            self._update_cache(path, depth)

    def _update_cache(self, path: str, depth: int):
        info_message("Checking", path, "for projects")
        # TODO: use os.walk()? Slower but more portable
        dotgitDirsList = subprocess.check_output(['find', path, '-maxdepth', str(depth),
                                                  '-name', '.git', '-print0']).decode('utf-8').split('\0')
        # -printf does not work on FreeBSD
        # we need to go up one dir from .git and use the absolute path
        dirsList = [os.path.realpath(os.path.dirname(p)) for p in dotgitDirsList if p]
        info_message(list(dirsList))
        for d in dirsList:
            repoName = os.path.basename(d)
            if repoName not in self.cache_data:
                info_message('Adding repo', d, 'in', repoName)
                self.cache_data[repoName] = [d]
            elif d not in self.cache_data[repoName]:
                info_message('Adding', d, 'as another repo for', repoName)
                self.cache_data[repoName].append(d)
            else:
                info_message('Repo', d, 'already exists in cache')
        # info_message(json.dumps(self.cache_data))
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
        # make a copy since we are modifying while iterating
        cache_data_copy = dict(self.cache_data)
        if len(self.cache_data) == 0:
            info_message("Cache is empty")
            sys.exit(0)
        changed = False
        for key, values in self.cache_data.items():
            # info_message("key =", key, "values=", values)
            for path in values:
                if not os.path.isdir(path):
                    changed = True
                    if len(values) > 1:
                        values.remove(path)
                        cache_data_copy[key] = values
                        info_message("Removed", path, "from cache for", key)
                        info_message("   remaining paths are:", values)
                    else:
                        del cache_data_copy[key]
                        info_message("Removed ", key, " (", path, ") from cache as it no longer exists", sep='')
        if not changed:
            info_message("All entries in cache are valid.")
        # noinspection PyUnresolvedReferences
        if not args.pretend:
            with open(self.cache_file, 'w+') as f:
                json.dump(cache_data_copy, f, indent=4)
                f.flush()

if __name__ == "__main__":
    # FIXME: handle CWD being deleted
    realCwd = os.path.realpath(os.getcwd() + '/')
    parser = argparse.ArgumentParser()
    parser.add_argument('--debug', action="store_true", help='Don\'t actually cleanup the cache, only print actions')
    subparsers = parser.add_subparsers(dest='subparser_name', help='sub-command help')
    devel_dirs = None
    parser_source = subparsers.add_parser('source', help='Get path to source dir')
    parser_source.add_argument('repository_name', default='', nargs='?', help='The name of the repository')
    parser_source.set_defaults(func=lambda args: devel_dirs.get_source_dir(args.repository_name))

    parser_build = subparsers.add_parser('build', help='Get path to build dir')
    parser_build.add_argument('repository_name', default='', nargs='?', help='The name of the repository')
    parser_build.set_defaults(func=lambda args: devel_dirs.get_build_dir(args.repository_name))

    parser_cache_lookup = subparsers.add_parser('cache-lookup', help='Get all repositories that start with given prefix')
    parser_cache_lookup.add_argument('name_prefix', help='The first few characters of the name')
    parser_cache_lookup.set_defaults(func=lambda args: devel_dirs.cache_lookup(args))

    parser_update_cache = subparsers.add_parser('update-cache', help='Update the source dirs cache')
    parser_update_cache.add_argument('path', nargs='?', default=None, help='The path where repositories are searched for')
    parser_update_cache.add_argument('depth', nargs='?', default=None, type=int,
                                     help='The search depth for finding repositories')
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
