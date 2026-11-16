"""Writes android/build_info.py from the GitHub Actions environment. A script (not shell text in the
workflow) so that nothing can be damaged by copying the workflow through a chat or an editor."""
import os
import re

number = re.sub(r"[^0-9]", "", os.environ.get("GITHUB_RUN_NUMBER", "")) or "dev"
sha = re.sub(r"[^0-9a-f]", "", os.environ.get("GITHUB_SHA", "").lower())[:7] or "local"
path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "android", "build_info.py")
with open(path, "w") as f:
    f.write('NUMBER = "%s"\nSHA = "%s"\n' % (number, sha))
print(open(path).read())
