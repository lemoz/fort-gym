FROM sha256:ebc48ef1e63dabcae0e624e92eb114bbfd5e21d96bb9d5a2a3e0f0c2a0426cc9
COPY source.bundle /tmp/keyboard-binding-source.bundle
RUN git fetch /tmp/keyboard-binding-source.bundle HEAD && git checkout --detach 8b9fffa1de4f93506cbcbdf82fd154aeb17b5697 && test -z "$(git status --porcelain --untracked-files=all)"
