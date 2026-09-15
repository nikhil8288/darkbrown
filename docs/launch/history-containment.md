# Repository exposure containment — owner review required

No step in this document has been executed. Repository visibility changes,
history rewriting, release deletion and force-pushes require explicit owner
authorization.

## Confirmed scope

- The GitHub repository is currently public.
- Operational loader data exists in prior Git history even though the current
  checkout now contains only synthetic fixtures.
- Deleting or replacing files in the current tree does not remove earlier
  blobs, clones, forks, caches or downloaded distributions.

## Proposed containment sequence

1. Freeze pushes and record every protected branch, tag, release, deployment
   reference and collaborator who must re-clone.
2. Change the repository to private and revoke public release artifacts only
   after the owner approves the exact affected surfaces.
3. Create and verify an encrypted offline `git bundle --all` recovery backup.
   Restrict the bundle as sensitive incident material.
4. In a disposable mirror clone, use `git filter-repo` to remove every
   historical `darkbrown/load/data/*.csv` and its historical manifest from all
   branches and tags. Re-add only the reviewed synthetic fixture set in a new
   commit.
5. Run a secret scanner against the rewritten mirror without copying matches
   into tickets or logs. Rotate any credential or token found; history cleanup
   is not credential revocation.
6. Verify the rewritten object database no longer contains the removed paths
   or approved private fingerprints, rebuild the wheel, and rerun the launch
   test suite.
7. Present old/new refs, affected branches/tags, object-count evidence,
   collaborator re-clone instructions and the rollback bundle for final owner
   approval. Only then force-push the reviewed refs.
8. Treat prior clones/forks/caches as an incident-response limitation; Git
   rewriting cannot recall copies already obtained.

## Rollback

Stop new writes, restore refs from the verified encrypted bundle to a private
remote, and require a clean re-clone. Do not merge old-history branches back
into the sanitized repository.
