# Dependency notice follow-up, November 8

The [updated inventory](../../LICENSES/dependency-inventory-20261108.json)
keeps the 804 entries from the verified November 4 environments. It adds notice
evidence; it does not claim a fresh dependency resolution or a Linux container
SBOM. The November 4 inventory and release archive remain unchanged.

Thirteen of the original 26 notice-collection gaps now have collected texts:
Azure Speech, esbuild's macOS binary package, four Next.js packages, Rollup's
macOS binary package, both unrs entries, imurmurhash, sharp-libvips, saxes and
esrecurse. Sources and hashes are attached to each inventory record.

Azure Speech already shipped LICENSE.md, ThirdPartyNotices.md and REDIST.txt
inside its installed wheel. The old collector missed the actual file layout
and could not decode all files as UTF-8. Original bytes are retained in
`LICENSES/collected-20261108/`; the readable bundle records decoding explicitly.
Its wheel metadata labels it Other/Proprietary, and the included license is the
Microsoft Speech SDK terms. Collecting those texts does not relicense the SDK.

Most recovered npm notices came from the published package's immutable gitHead.
imurmurhash used a matching version tag; esrecurse has its license inside its
published README. The libvips LGPL text is collected, but binary redistribution
and transitive native-component notices need their own artifact review.

Thirteen complete, version-matched notice gaps remain:

- `@open-draft/deferred-promise@2.2.0`
- `@types/json5@0.0.29`
- `client-only@0.0.1`
- `is-node-process@1.2.0`
- `keyv@4.5.4`
- `language-tags@1.0.9`
- `natural-compare@1.4.0`
- `react-remove-scroll-bar@2.3.8`
- `stable-hash@0.0.5`
- `stackback@0.0.2`
- `strict-event-emitter@0.5.1`
- `use-composed-ref@1.4.0`
- `language-subtag-registry@0.3.23`

These entries retain declared license metadata, available README license
excerpts, corresponding source revisions or the explicit reason a revision
could not be established. A declared license or an attribution-only paragraph
was not substituted for a missing complete notice. These are evidence gaps,
not findings that the packages are unlicensed.

Preserve both dated dependency-notice bundles. The source candidate does not
bundle installed packages, CLI binaries, model weights or container images.
The inventory is evidence for distribution review, not a legal clearance.
