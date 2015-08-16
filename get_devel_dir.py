#!/usr/bin/env python3

import json
import sys
import os
import subprocess

builddir = os.getenv("CURRENT_BUILD_ROOT") or "/build/"
if not builddir.endswith("/"):
    builddir += "/"

sourcedirs = ["/home/alex/devel/", "/staticdata/sources/"]


def updateCache(path, depth, cacheData, cacheFilePath):
    dirs = subprocess.check_output(['find', path, '-maxdepth', str(depth), '-type', 'd',
                                    '-name', '.git', '-printf', '%h\\0'])
    dirsList = dirs.decode('utf-8').split('\0')
    print(dirsList)
    for d in dirsList:
        if not d:
            continue
        d = os.path.realpath(d)
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


def findInCache(path: str, cacheData):
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


if "--help" in sys.argv:
    print("Usage: get_devel_dir.py source|build|update-cache [dir]")
    sys.exit()

if len(sys.argv) < 2:
    sys.exit("Need at least one argument!")

type = sys.argv[1]
path = sys.argv[2] if len(sys.argv) >= 3 else ""
realCwd = os.path.realpath(os.getcwd() + '/')

cacheDir = os.getenv("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))
cacheFilePath = os.path.join(cacheDir, "devel-dirs.cache")
cacheData = {}
try:
    # try:
    with open(cacheFilePath, 'r') as cacheFile:
        cacheData = json.load(cacheFile)
except:
    print('Cache data was invalid, assuming empty!', file=sys.stderr)

if type == "build":
    cachedSourceDir = findInCache(path, cacheData)
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
elif type == "source":
    cachedSourceDir = findInCache(path, cacheData)
    if cachedSourceDir:
        output_result(cachedSourceDir)
    for sourcedir in sourcedirs:
        if realCwd.startswith(sourcedir) or realCwd == sourcedir:
            sys.stderr.write("Already in source dir.\n")
            output_result(realCwd)

    def getCorrespondingSourceDir(path):
        for dir in sourcedirs:
            srcdir = path.replace(builddir, dir)
            # print("checking ", srcdir, file=sys.stderr)
            if os.path.isdir(srcdir):
                output_result(srcdir)
        print("Could not find source dir for", path, file=sys.stderr)
        output_result(path)
    # path might be empty in that case this condition will always be false
    if path.startswith(builddir):
        getCorrespondingSourceDir(path)
    elif realCwd.startswith(builddir):
        getCorrespondingSourceDir(realCwd)
    else:
        # not in source dir before -> change to source dir root
        output_result(sourcedirs[0])
elif type == "update-cache":
    depth = sys.argv[3] if len(sys.argv) >= 4 else 2

    print('saving to', cacheFilePath, file=sys.stderr)
    updateCache(path, depth, cacheData, cacheFilePath)
elif type == "cache-lookup":
    # return all possibilities when no arg passed, otherwise filter
    candidates = []
    if len(path) > 0:
        for k in cacheData.keys():
            if k.startswith(path):
                candidates.append(k)
    else:
        # just return all of them
        candidates = cacheData.keys()
    output_result(" ".join(candidates))
elif type == "check-cache":
    if len(cacheData) == 0:
        print("Cache is empty")
        sys.exit(0)
    for key, values in cacheData.items():
        # print("key =", key, "values=", values)
        for path in values:
            if not os.path.isdir(path):
                print(key, "->", path, "no longer exists!")
elif type == "cleanup-cache":
    # make a copy since we are modifying while iterating
    cacheDataCopy = dict(cacheData)
    if len(cacheData) == 0:
        print("Cache is empty")
        sys.exit(0)
    for key, values in cacheData.items():
        # print("key =", key, "values=", values)
        for path in values:
            if not os.path.isdir(path):
                if len(values) > 1:
                    values.remove(path)
                    cacheDataCopy[key] = values
                    print("Removed", path, "from cache for", key)
                    print("   remaining paths are:", values)
                else:
                    del cacheDataCopy[key]
                    print("Removed", key, "from cache as it no longer exists")
    with open(cacheFilePath, 'w+') as cacheFile:
        json.dump(cacheDataCopy, cacheFile, indent=4)
        cacheFile.flush()
elif type == "bash-complete":
    # argv[0]: command
    # argv[1]: "bash-complete"
    # argv[2]: command to complete (get_devel_dir.py)
    # argv[3]: current word
    # argv[4]: previous word
    # print(sys.argv)
    # raise RuntimeError()
    pass
else:
    sys.exit("Type must be be eiter 'build' or 'source'")
