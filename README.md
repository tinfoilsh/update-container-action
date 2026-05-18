# update-container-action

This Github Action prepares a Tinfoil Container repository for measurement and release.
It can:

- Update tinfoil-config.yml with new container hashes
- Create version tags

## Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `version` | yes | — | Version tag to create (e.g. `v0.0.6`). |
| `source-sha` | yes | — | The commit that the container image(s) were built from. Pass `${{ github.sha }}`. |
| `github-token` | yes | — | Token used to push the tag (see note below). |
| `image-refs` | when `update-config` is `true` | — | Image references in `<repo>@sha256:<digest>` format, one per line. |
| `update-config` | no | `false` | Substitute the digests into `tinfoil-config.yml` in the tagged commit. |

> **`github-token`:** pushing a tag with the default `GITHUB_TOKEN` does **not**
> trigger other workflows. If a downstream workflow (e.g. measurement, GitHub
> release) runs on the new tag, pass a PAT or GitHub App token instead.

## Usage

### External Container Workflow

If you are using a container built outside of your repo (i.e. you already know the hash), then you can update the container hash manually.
This action will only create the new version tag for you.

```yaml
- uses: tinfoilsh/update-container-action@<commit-sha>
  with:
    version: ${{ inputs.version }}
    source-sha: ${{ github.sha }}
    github-token: ${{ secrets.GITHUB_TOKEN }}
```

### Integrated Container Workflow

If your container image is built as part of your release flow, this action can automatically update the image hashes in `tinfoil-config.yml` before tagging the new version.

```yaml
prepare-release:
  needs: container-build
  runs-on: ubuntu-latest
  permissions:
    contents: write
  steps:
    - uses: tinfoilsh/update-container-action@<commit-sha>
      with:
        version: ${{ inputs.version }}
        source-sha: ${{ github.sha }}
        update-config: true
        image-refs: "ghcr.io/tinfoilsh/my-container@${{ needs.container-build.outputs.digest }}"
        github-token: ${{ secrets.GITHUB_TOKEN }}
```

For multiple container images, pass a newline-separated list of references:

```yaml
      with:
        version: ${{ inputs.version }}
        source-sha: ${{ github.sha }}
        update-config: true
        image-refs: |
          ghcr.io/tinfoilsh/c1@${{ needs.build1.outputs.digest }}
          ghcr.io/tinfoilsh/c2@${{ needs.build2.outputs.digest }}
        github-token: ${{ secrets.GITHUB_TOKEN }}
```

## Permissions

The workflow needs:

```yaml
permissions:
  contents: write
```

## Config Update Details

When `update-config: true`, the repository must contain a `tinfoil-config.yml`
with an image reference whose value is in `<repo>:<tag>` or `<repo>@<digest>`
form — for example, a placeholder digest:

```yaml
image: "ghcr.io/tinfoilsh/my-container@sha256:0000000000000000000000000000000000000000000000000000000000000000" # placeholder
```

To perform the update, the action will create a commit updating the hashes.
The commit is based off the same commit that was used to build the images and will not be merged back into the main branch.
The release tag points to this commit.
This is intentional to prevent race conditions that can occur if new commits are merged into the main branch while this action is running.
This could result in inconsistent measurements.

As a result, the repository has the following structure:

```
              o <-- v1.0.0      o <-- v1.1.0
             /                 /
main  o-----o-----o-----o-----o-----o-----o--->
```
