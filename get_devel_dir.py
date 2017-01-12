#!/usr/bin/env python3

import json
import sys
import os
import subprocess
import argparse

builddir = os.getenv("CURRENT_BUILD_ROOT")
if not builddir:
    sys.exit("CURRENT_BUILD_ROOT environment variable must be set to the root build dir (e.g. '/build/')")
if not builddir.endswith("/"):
    builddir += "/"

if not os.getenv("CURRENT_SOURCE_ROOT"):
    sys.exit("CURRENT_SOURCE_ROOT environment variable must be set to a colon separated list of source dirs"
             " (e.g. '/local/sources:/foo/bar/src/')")
sourcedirs = os.getenv("CURRENT_SOURCE_ROOT").split(":")
# remove empty entries (e.g. if it ends with a colon we don't want to add / as a source dir)
sourcedirs = filter(None, sourcedirs)
# make sure all of them end with a slash
sourcedirs = [d if d.endswith("/") else d + "/" for d in sourcedirs]
# print("sourcedirs:", sourcedirs, "builddir:", builddir, file=sys.stderr)


def findInCache(path: str, cacheData: dict):
    if not path or '/' in path:
        return None
    # print("Finding repo", path, file=sys.stderr)
    if path not in cacheData:
        print("Could not find repository", path, file=sys.stderr)
        sys.exit(1)
    dirs = cacheData[path]
    if len(dirs) == 0:
        print("Corrupted cache file:", path, "is empty!", file=sys.stderr)
        sys.exit(1)
    elif len(dirs) == 1:
        return dirs[0]
    print("Multiple source directories found for name", path, file=sys.stderr)
    for i, s in enumerate(dirs):
        print('  [' + str(i + 1) + ']', s, file=sys.stderr)
    chosen = "<none>"
    try:
        # input prompts on stdout, but we read stdout -> print to stderr instead
        print('Which one did you mean? ', file=sys.stderr, end='')
        chosen = input()
        if int(chosen) < 1 or int(chosen) > len(dirs):
            raise RuntimeError("Out of range")
        return dirs[int(chosen) - 1]
    except:
        sys.exit('Invalid choice: ' + chosen)


def output_result(r):
    print(r)
    sys.exit()


def get_build_dir(args: argparse.Namespace):
    cachedSourceDir = findInCache(args.repository_name, cacheData)
    if cachedSourceDir:
        path = cachedSourceDir
    else:
        path = realCwd
    if path.startswith(builddir) or path == builddir:
        sys.stderr.write("Already in build dir.\n")
        output_result(path)
    for sourcedir in sourcedirs:
        if path.startswith(sourcedir):
            output_result(path.replace(sourcedir, builddir))
    # not in source dir before -> change to build dir root
    output_result(builddir)


def get_source_dir(args: argparse.Namespace):
    cachedSourceDir = findInCache(args.repository_name, cacheData)
    if cachedSourceDir:
        output_result(cachedSourceDir)
    for sourcedir in sourcedirs:
        if realCwd.startswith(sourcedir) or realCwd == sourcedir:
            sys.stderr.write("Already in source dir.\n")
            output_result(realCwd)

    def getCorrespondingSourceDir(path):
        for dir in sourcedirs:
            if not dir.endswith("/"):
                dir += "/"
            srcdir = path.replace(builddir, dir)
            # print("checking ", srcdir, file=sys.stderr)
            if os.path.isdir(srcdir):
                output_result(srcdir)
        print("Could not find source dir for", path, file=sys.stderr)
        output_result(path)
    # path might be empty in that case this condition will always be false
    if args.repository_name.startswith(builddir):
        getCorrespondingSourceDir(args.repository_name)
    elif realCwd.startswith(builddir):
        getCorrespondingSourceDir(realCwd)
    else:
        # not in source dir before -> change to source dir root
        output_result(sourcedirs[0])


def update_cache(args: argparse.Namespace):
    print('saving to', cacheFilePath, file=sys.stderr)
    dotgitDirsList = subprocess.check_output(['find', args.path, '-maxdepth', str(args.depth),
                                              '-name', '.git', '-print0']).decode('utf-8').split('\0')
    # -printf does not work on FreeBSD
    # we need to go up one dir from .git and use the absolute path
    dirsList = [os.path.realpath(os.path.dirname(p)) for p in dotgitDirsList if p]
    print(list(dirsList), file=sys.stderr)
    for d in dirsList:
        repoName = os.path.basename(d)
        if repoName not in cacheData:
            print('Adding repo', d, 'in', repoName, file=sys.stderr)
            cacheData[repoName] = [d]
        elif d not in cacheData[repoName]:
            print('Adding', d, 'as another repo for', repoName, file=sys.stderr)
            cacheData[repoName].append(d)
        else:
            print('Repo', d, 'already exists in cache', file=sys.stderr)
    # print(json.dumps(cacheData), file=sys.stderr)
    with open(cacheFilePath, 'w+') as cacheFile:
        json.dump(cacheData, cacheFile, indent=4)
        cacheFile.flush()


def cache_lookup(args: argparse.Namespace):
    # return all possibilities when no arg passed, otherwise filter
    candidates = []
    if len(args.name_prefix) > 0:
        for k in cacheData.keys():
            if k.startswith(args.name_prefix):
                candidates.append(k)
    else:
        # just return all of them
        candidates = cacheData.keys()
    output_result(" ".join(candidates))


def cleanup_cache(args: argparse.Namespace):
    # make a copy since we are modifying while iterating
    cacheDataCopy = dict(cacheData)
    if len(cacheData) == 0:
        print("Cache is empty", file=sys.stderr)
        sys.exit(0)
    changed = False
    for key, values in cacheData.items():
        # print("key =", key, "values=", values)
        for path in values:
            if not os.path.isdir(path):
                changed = True
                if len(values) > 1:
                    values.remove(path)
                    cacheDataCopy[key] = values
                    print("Removed", path, "from cache for", key, file=sys.stderr)
                    print("   remaining paths are:", values, file=sys.stderr)
                else:
                    del cacheDataCopy[key]
                    print("Removed ", key, " (", path, ") from cache as it no longer exists", sep='', file=sys.stderr)
    if not changed:
        print("All entries in cache are valid.", file=sys.stderr)
    if not args.pretend:
        with open(cacheFilePath, 'w+') as f:
            json.dump(cacheDataCopy, f, indent=4)
            f.flush()


realCwd = os.path.realpath(os.getcwd() + '/')

cacheDir = os.getenv("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))
cacheFilePath = os.path.join(cacheDir, "devel-dirs.cache")
cacheData = {}
try:
    with open(cacheFilePath, 'r') as cacheFile:
        cacheData = json.load(cacheFile)
except:
    print('Cache data was invalid, assuming empty!', file=sys.stderr)

parser = argparse.ArgumentParser()
subparsers = parser.add_subparsers(dest='subparser_name', help='sub-command help')

parser_source = subparsers.add_parser('source', help='Get path to source dir')
parser_source.add_argument('repository_name', default='', nargs='?', help='The name of the repository')
parser_source.set_defaults(func=get_source_dir)

parser_build = subparsers.add_parser('build', help='Get path to build dir')
parser_build.add_argument('repository_name', default='', nargs='?', help='The name of the repository')
parser_build.set_defaults(func=get_build_dir)

parser_cache_lookup = subparsers.add_parser('cache-lookup', help='Get all repositories that start with given prefix')
parser_cache_lookup.add_argument('name_prefix', help='The first few characters of the name')
parser_cache_lookup.set_defaults(func=cache_lookup)

parser_update_cache = subparsers.add_parser('update-cache', help='Update the source dirs cache')
parser_update_cache.add_argument('path', nargs='?', default='.', help='The path where repositories are searched for')
parser_update_cache.add_argument('depth', nargs='?', default='2', type=int,
                                 help='The search depth for finding repositories')
parser_update_cache.set_defaults(func=update_cache)

parser_cleanup_cache = subparsers.add_parser('cleanup-cache', help='Update the source dirs cache')
parser_cleanup_cache.add_argument('--pretend', '-p', action="store_true",
                                  help='Don\'t actually cleanup the cache, only print actions')
parser_cleanup_cache.set_defaults(func=cleanup_cache)

# parse the args and call whatever function was selected
parsed_args = parser.parse_args()
parsed_args.func(parsed_args)
