#!/usr/bin/env python3

import json
import sys
import os
import subprocess
import argparse
import itertools
import typing


def debug(*args, **kwargs):
    if False:
        print("\x1b[1;33m", end="", file=sys.stderr)
        print(*args, file=sys.stderr, end="", **kwargs)
        print("\x1b[0m", file=sys.stderr)


def warning(*args, **kwargs):
    print(*args, **kwargs, file=sys.stderr)


def die(*args, **kwargs):
    print(*args, **kwargs, file=sys.stderr)
    sys.exit(1)

def output_result(r):
    print(r, file=sys.stdout)
    sys.exit()


# A class that lazily computes the real path
class Directory(object):
    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        if not self.path.endswith("/"):
            self.path += "/"
        self.__real_path = None  # type: str

    @property
    def real_path(self):
        if self.__real_path is None:
            self.__real_path = os.path.realpath(self.path)
            assert self.__real_path.startswith("/")
        return self.__real_path

    def is_subdirectory_of(self, other: "Directory"):
        assert isinstance(other, Directory)
        if self.path.startswith(other.path) or self.real_path.startswith(other.path):
            return True
        if self.path.startswith(other.real_path) or self.real_path.startswith(other.real_path):
            return True
        return False

    def try_replace_prefix(self, prefix: "Directory", replacement: str) -> str:
        for src, dest in itertools.product((self.path, self.real_path), (prefix.path, prefix.real_path)):
            if src.startswith(dest):
                return src.replace(dest, replacement)
        return None


class DevelDirs(object):
    def __init__(self):
        config_file = os.path.join(os.getenv("XDG_CACHE_HOME", os.path.expanduser("~/.config")), "devel_dirs.json")
        with open(config_file, 'r') as f:
            self.config_data = json.load(f)  # type: dict

        ensure_trailing_slash = lambda s: s if s.endswith("/") else s + "/"
        # remove empty entries (e.g. if it ends with a colon we don't want to add / as a source dir)
        self.build_dirs = list(filter(None, map(os.path.expandvars, map(ensure_trailing_slash, self.config_data["build-dirs"]))))
        self.source_dirs = list(filter(None, map(os.path.expandvars, map(ensure_trailing_slash, self.config_data["source-dirs"]))))
        # TODO: move to where it's needed
        self.src_to_build_mapping = itertools.zip_longest(self.source_dirs, self.build_dirs,
                                                          fillvalue=self.build_dirs[0])
        if len(self.build_dirs) > len(self.source_dirs):
            die("Cannot have more build dirs than source dirs")
        debug("source dirs:", self.source_dirs, "build dirs:", self.build_dirs)
        debug("mapping:", dict(self.src_to_build_mapping))

        # Load the cache file:
        cacheDir = os.getenv("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))
        self.cache_file = os.path.join(cacheDir, "devel-dirs.cache")
        try:
            with open(self.cache_file, 'r') as f:
                self.cache_data = json.load(f)
        except IOError:
            self.cache_data = {}
            print('Cache data was invalid, assuming empty!', file=sys.stderr)
        debug("Cache data:", self.cache_data)

    def get_dir_for_repo(self, repo_name: str) -> typing.Optional[Directory]:
        debug("Finding repo", repo_name)
        if repo_name not in self.cache_data:
            warning("Could not find repository", repo_name)
            return None
        dirs = self.cache_data[repo_name]
        if len(dirs) == 0:
            die("Corrupted cache file:", repo_name, "is empty!")
        elif len(dirs) == 1:
            return Directory(dirs[0])
        print("Multiple source directories found for name", repo_name, file=sys.stderr)
        for i, s in enumerate(dirs):
            print('  [' + str(i + 1) + ']', s, file=sys.stderr)
        chosen = "<none>"
        try:
            # input prompts on stdout, but we read stdout -> print to stderr instead
            print('Which one did you mean? ', file=sys.stderr, end='')
            chosen = input()
            if int(chosen) < 1 or int(chosen) > len(dirs):
                raise RuntimeError("Out of range")
            return Directory(dirs[int(chosen) - 1])
        except:
            sys.exit('Invalid choice: ' + chosen)

    def get_build_dir(self, args: argparse.Namespace):
        if args.repository_name:
            path = self.get_dir_for_repo(args.repository_name)
        else:
            path = Directory(os.path.realpath(os.getcwd()))

        # check if we are already in a build dir:
        for build_dir in self.build_dirs:
            if path.is_subdirectory_of(Directory(build_dir)):
                sys.stderr.write("Already in build dir.\n")
                output_result(path)

        # check whether a custom mapping exists:
        overrides = self.config_data.get("overrides", {})
        debug("overrides:", overrides)
        for override in overrides:
            override_src = Directory(override["source"])
            new_dir = path.try_replace_prefix(override_src, override["build"])
            if new_dir:
                output_result(new_dir)

        for src, build in self.src_to_build_mapping:
            new_dir = path.try_replace_prefix(Directory(src), build)
            if new_dir:
                output_result(new_dir)

        # final fallback: not in build dir before -> change to build dir root
        output_result(self.build_dirs[0])

    def get_source_dir(self, args: argparse.Namespace):
        if args.repository_name:
            cachedSourceDir = self.get_dir_for_repo(args.repository_name)
            if cachedSourceDir:
                output_result(cachedSourceDir.path)
            else:
                die("Cannot find repository for", args.repository_name)

        # find the matching source dir for CWD
        cwd = Directory(os.getcwd())
        for src in self.source_dirs:
            if cwd.is_subdirectory_of(Directory(src)):
                sys.stderr.write("Already in source dir.\n")
                output_result(cwd.path)

        # check whether a custom mapping exists:
        overrides = self.config_data.get("overrides", {})
        debug("overrides:", overrides)
        for override in overrides:
            override_build = Directory(override["build"])
            new_dir = cwd.try_replace_prefix(override_build, override["source"])
            if new_dir:
                output_result(new_dir)

        for src, build in self.src_to_build_mapping:
            new_dir = cwd.try_replace_prefix(Directory(build), src)
            if new_dir:
                output_result(new_dir)

        # final fallback: not in source dir before -> change to default source dir
        output_result(self.source_dirs[0])

    def update_cache(self, args: argparse.Namespace):
        print('saving to', self.cache_file, file=sys.stderr)
        dotgitDirsList = subprocess.check_output(['find', args.path, '-maxdepth', str(args.depth),
                                                  '-name', '.git', '-print0']).decode('utf-8').split('\0')
        # -printf does not work on FreeBSD
        # we need to go up one dir from .git and use the absolute path
        dirsList = [os.path.realpath(os.path.dirname(p)) for p in dotgitDirsList if p]
        print(list(dirsList), file=sys.stderr)
        for d in dirsList:
            repoName = os.path.basename(d)
            if repoName not in self.cache_data:
                print('Adding repo', d, 'in', repoName, file=sys.stderr)
                self.cache_data[repoName] = [d]
            elif d not in self.cache_data[repoName]:
                print('Adding', d, 'as another repo for', repoName, file=sys.stderr)
                self.cache_data[repoName].append(d)
            else:
                print('Repo', d, 'already exists in cache', file=sys.stderr)
        # print(json.dumps(self.cache_data), file=sys.stderr)
        with open(self.cache_file, 'w+') as cacheFile:
            json.dump(self.cache_data, cacheFile, indent=4)
            cacheFile.flush()

    def cache_lookup(self, args: argparse.Namespace):
        # return all possibilities when no arg passed, otherwise filter
        candidates = []
        if len(args.name_prefix) > 0:
            for k in self.cache_data.keys():
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
            print("Cache is empty", file=sys.stderr)
            sys.exit(0)
        changed = False
        for key, values in self.cache_data.items():
            # print("key =", key, "values=", values)
            for path in values:
                if not os.path.isdir(path):
                    changed = True
                    if len(values) > 1:
                        values.remove(path)
                        cache_data_copy[key] = values
                        print("Removed", path, "from cache for", key, file=sys.stderr)
                        print("   remaining paths are:", values, file=sys.stderr)
                    else:
                        del cache_data_copy[key]
                        print("Removed ", key, " (", path, ") from cache as it no longer exists", sep='', file=sys.stderr)
        if not changed:
            print("All entries in cache are valid.", file=sys.stderr)
        if not args.pretend:
            with open(self.cache_file, 'w+') as f:
                json.dump(self.cache_data_copy, f, indent=4)
                f.flush()

if __name__ == "__main__":
    # FIXME: handle CWD being deleted
    realCwd = os.path.realpath(os.getcwd() + '/')
    devel_dirs = DevelDirs()
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='subparser_name', help='sub-command help')

    parser_source = subparsers.add_parser('source', help='Get path to source dir')
    parser_source.add_argument('repository_name', default='', nargs='?', help='The name of the repository')
    parser_source.set_defaults(func=lambda args: devel_dirs.get_source_dir(args))

    parser_build = subparsers.add_parser('build', help='Get path to build dir')
    parser_build.add_argument('repository_name', default='', nargs='?', help='The name of the repository')
    parser_build.set_defaults(func=lambda args: devel_dirs.get_build_dir(args))

    parser_cache_lookup = subparsers.add_parser('cache-lookup', help='Get all repositories that start with given prefix')
    parser_cache_lookup.add_argument('name_prefix', help='The first few characters of the name')
    parser_cache_lookup.set_defaults(func=lambda args: devel_dirs.cache_lookup(args))

    parser_update_cache = subparsers.add_parser('update-cache', help='Update the source dirs cache')
    parser_update_cache.add_argument('path', nargs='?', default='.', help='The path where repositories are searched for')
    parser_update_cache.add_argument('depth', nargs='?', default='2', type=int,
                                     help='The search depth for finding repositories')
    parser_update_cache.set_defaults(func=lambda args: devel_dirs.update_cache(args))

    parser_cleanup_cache = subparsers.add_parser('cleanup-cache', help='Update the source dirs cache')
    parser_cleanup_cache.add_argument('--pretend', '-p', action="store_true",
                                      help='Don\'t actually cleanup the cache, only print actions')
    parser_cleanup_cache.set_defaults(func=lambda args: devel_dirs.cleanup_cache(args))

    # parse the args and call whatever function was selected
    parsed_args = parser.parse_args()
    parsed_args.func(parsed_args)
