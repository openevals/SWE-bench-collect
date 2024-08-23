#!/usr/bin/env bash

_DEBUG="on"
function DEBUG()
{
 [ "$_DEBUG" == "on" ] &&  $@
}
 
# DEBUG set -x

set -euo pipefail

REPO_TARGET=$1

gh repo view "$REPO_TARGET" > /dev/null || exit 1

NEW_REPO_NAME="./data/repos/${REPO_TARGET//\//__}" 

echo "** Cloning from remote repository $REPO_TARGET to your local repository $NEW_REPO_NAME..."
TARGET_REPO_DIR="./data/repos/${REPO_TARGET##*/}.GIT"

if [ -d "$NEW_REPO_NAME" ]; then
  echo "The local repository $TARGET_REPO_DIR already exists. Skipping."
else
  git clone git@github.com:$REPO_TARGET.git ${NEW_REPO_NAME}
fi

if [ $? -ne 0 ]; then
  echo "Failed to clone the repository."
  exit 1
fi

echo "Done! 😊"
DEBUG set +x
