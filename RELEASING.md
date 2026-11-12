# Releasing Agnostos

The versions follow [SemVer](https://semver.org/). The version is written in only one place:
`outreach/__init__.py` (`pyproject.toml` reads it from there).

1. Move the `## [Unreleased]` notes in `CHANGELOG.md` below a new
   `## [X.Y.Z] - YYYY-MM-DD` heading. Update the compare links.
2. Set `__version__ = "X.Y.Z"` in `outreach/__init__.py`.
3. Commit: `git commit -am "release: vX.Y.Z"`.
4. Add the tag and push:
   ```
   git tag -a vX.Y.Z -m "Agnostos vX.Y.Z"
   git push origin main vX.Y.Z
   ```

The `release` workflow makes sure that the tag is the same as `__version__`, and it runs
the tests. Then it attaches the wheel and the sdist to a GitHub Release (with
the notes from `CHANGELOG.md`). It also pushes
`ghcr.io/avinashistoocool/agnostos:{X.Y.Z, X.Y, latest}`.

## Deploying

```
pip install "agnostos[calendar] @ git+https://github.com/Avinashistoocool/Agnostos-v2@vX.Y.Z"
# or
docker pull ghcr.io/avinashistoocool/agnostos:X.Y.Z
docker compose up -d        # see compose.yaml
```
