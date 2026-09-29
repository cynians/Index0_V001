# Oak foliage and the 32-pixel leaf

Oak now uses separate primary branches, secondary limbs, fine twigs and current
shoots. Individual botanical leaves attach at explicit nodes along each shoot's
local direction. Mixed long/short distribution adds separate short leafy shoots.

The final sprite is exactly **32 × 32 pixels**, with binary transparency and
three used opaque green colours, accompanied by an editable Pixel Studio file:

- `assets/illustrations/illust_quercus_robur_leaf_32_pixel.png`
- `assets/illustrations/illust_quercus_robur_leaf_32_pixel.layers.json.gz`

Oak now references `illust_quercus_robur_leaf_32`, with a .10 m depicted leaf
length, small size class and attachment anchor (16,29) on the pixel canvas.
Previous fields are in `artifacts/oak_foliage/oak_leaf_fields_before.json`;
other organ anchors were preserved.

Image generation used edit mode from the initial high-detail draft, followed
by import to the exact grid/palette through native Pixel Studio in
`tools/author_oak_leaf_pixel.py`. Final generation prompt:

> Transform the referenced oak leaf into a strict 32 by 32 logical pixel-art sprite for a low-resolution plant simulation. Use a 32x32 grid, shown enlarged with hard nearest-neighbour square pixels. Exactly one oak leaf, upright with a short petiole at bottom centre. Simplify into 4 green colours total, large readable rounded lobes, central vein only. No photograph, texture, fine veins, gradients, dithering, antialiasing or shadows. True transparent background. One botanical leaf only, no twig or branch. Design occupies central 16-20 columns and rows 2 through 30 of the 32x32 grid. Every visible feature must align to the 32x32 pixel grid. Preserve recognizable lobed English oak leaf outline but simplify radically.

Rendering uses physical organ dimensions and nearest-neighbour sprites; explicit
cohorts do not receive duplicate legacy billboard leaves. Canonical leaf area
accounts for organ scale. Curve direction no longer depends on placement-index
parity, which changes with LOD. Authored reproductive organs stay separate.

Branches view provides secondary-limb and current-shoot foliage/skeleton views.
`py -m tools.render_oak_foliage` creates whole/detail panels and controlled
along-shoot, terminal and mixed distributions in `artifacts/oak_foliage_final/`.
Earlier rounds are retained nearby. These are renderer previews; mature crown
architecture remains approximate and has not been empirically calibrated.

[Kew's oak profile](https://powo.science.kew.org/taxon/urn:lsid:ipni.org:names:304293-2/general-information)
informs leaf morphology; [rhythmic oak growth research](https://pmc.ncbi.nlm.nih.gov/articles/PMC4765786/)
informs discontinuous shoot development. Branch budgets/cohort multipliers are
implementation defaults. The [Forest experiment](species_sim_forest_shade_v001.md)
uses this same organ representation for neighbour responses.
