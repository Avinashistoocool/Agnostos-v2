# Releasing Agnostos

Versions follow [SemVer](https://semver.org/). The only place the version is
written is `outreach/__init__.py` (`pyproject.toml` reads it from there).

1. Move the `## [Unreleased]` notes in `CHANGELOG.md` under a new
   `## [X.Y.Z] - YYYY-MM-DD` heading and update the compare links.
2. Set `__version__ = "X.Y.Z"` in `outreach/__init__.py`.
3. Commit: `git commit -am "release: vX.Y.Z"`.
4. Tag and push:
   ```
   git tag -a vX.Y.Z -m "Agnostos vX.Y.Z"
   git push origin main vX.Y.Z
   ```

The `release` workflow checks that the tag matches `__version__` and runs
the tests. It then attaches the wheel and sdist to a GitHub Release (with
the notes from `CHANGELOG.md`) and pushes
`ghcr.io/avinashistoocool/agnostos:{X.Y.Z, X.Y, latest}`.

## Deploying

```
pip install "agnostos[calendar] @ git+https://github.com/Avinashistoocool/Agnostos-v2@vX.Y.Z"
# or
docker pull ghcr.io/avinashistoocool/agnostos:X.Y.Z
docker compose up -d        # see compose.yaml
```
