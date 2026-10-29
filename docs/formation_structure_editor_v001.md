# Formation structure editor

Formation Sim's Design view treats `formation` as the only fixed structural
concept. A player can use the same nested entities for a fire team, a trade
convoy, a regiment, a fleet, or a whole army. Names such as platoon, escort,
warehouse group, and flotilla are authored labels, never inferred taxonomy.

The visual map keeps the direct roster beneath each formation's bracket.
Vehicles and personnel are grouped by authored role, with exact counts on the
symbols; large counts show a sample plus a remainder badge. Vehicle crew roles
are requirements linked to the chosen vehicle unless a formation overrides
them. Equipment, doctrine, support from ancestors, the faction owner, and the
current crew coverage appear beside that direct roster.

## Clickable structure commands

- `+ Formation` on any header creates a subordinate under that formation. It
  starts with the parent's faction owner when that owner is available; the
  separate owner picker can change it afterward. If no owner is available,
  creation uses the searchable faction picker.
- A formation symbol selects it; clicking the label area folds or opens it.
  The `Structure` menu can rename it, change its faction owner, change its
  command parent, promote it one level, reorder it among siblings, or fold/open
  all descendants.
- Personnel and vehicle symbols can be selected together. `Group selection`
  asks for an authored name and makes a subordinate under their common parent.
  Selection from different parents must first be moved to one parent.
- `Place selected here` moves selected roster slots and subordinate formations
  beneath the clicked target. A searchable parent picker is available for
  moving one formation or a selection. It searches names and ancestor paths.
- `Attach existing formation` searches the full formation catalog, including
  formations outside the current map, and places the chosen formation under
  the clicked command parent. Its owner and existing subordinates remain with
  it.

Structural parentage uses the formation `parents` relation. A command-parent
move preserves the entity's `faction` relation and the owners of its children.
Parent and attach pickers exclude choices that would create a structural
cycle. Blueprint organization, roster, equipment, and doctrine
changes continue to use sparse year snapshots; reordering and reparenting
update the affected parent blueprint organization snapshots.

The map measures all branches, then paints only those intersecting the
viewport. Fold commands and searchable target pickers keep hundreds of sibling
formations workable without placing every card on screen at once. The sidebar
remains a navigation aid; the visual map is the editor.

Renderer previews include `artifacts/formation_structure_trade_fleet_overview.png`,
`artifacts/formation_structure_trade_fleet_parent_picker.png`,
`artifacts/formation_structure_trade_fleet_attach_picker.png`, and
`artifacts/formation_structure_trade_fleet_new_subordinate.png`. They are
fixtures from `tools/render_formation_structure_preview.py`, not changes to
the persistent ontology. Formation editor and vehicle regression tests cover
the structure commands, owner preservation, crew requirements, and a
120-sibling map.

## Deck workspace (unit cards)

The third workspace tab, `Deck`, treats a formation as a deck built from
unit cards in the manner of WARNO. A unit card (dataset `unit_cards`,
`schema_unit_card`) is one deployable package a faction fields: the "GGO Sol
Marine Tank Platoon" is three tanks, and each tank brings the crew its vehicle
design lists in `crew_roles`. A card says what one copy takes from the world
when it is fielded (owner, 2026-10-29: no deck points, no per-deck limits;
cards consume equipment and manpower instead). Card fields: `faction` (blank
means any deck may use it), `card_category` (the deck tab; suggested labels
from Command to Space, any label works), `card_manpower` (people by role:
`{id, role, rank, count, is_command}`) and `card_equipment` (`{id, kind:
vehicle|item, vehicle|item: entity id, count}`). Transport is not chosen per
deck: a card that rides in something lists the vehicle in its equipment, and
the vehicle's crew count in the card's manpower.

A formation's deck is `deck_cards` (`[{card, count, short}]`). Strength is
counted from the cards, never stored. The header shows cards, vehicles, items
and people, the totals of subordinate formations' decks, where the deck draws
from and what it is short. Blueprint deck changes are recorded in the year
snapshots like other blueprint edits. Fielding is described below.

- The formation tree on the left picks which formation's deck is edited.
- The card list shows the formation faction's cards and unowned cards in
  service in the view year, with search and category filters. Clicking a card
  adds a copy; `Edit` opens it.
- Deck tiles group by category; `-`, `+` and `Edit` change copies or the card.
- `+ New card` opens the card editor: name and category; Manpower with
  `+ Personnel` (role, rank, count, lead marker) and a line for the crew the
  vehicles bring; Equipment with `+ Vehicle` (searchable, crew shown per
  vehicle) and `+ Item` (searchable, item category shown). A live preview and
  a "one copy takes" line sit beside it. The draft is written on `Save card`;
  a new card is added to the open deck.

`tools/author_unit_card_model.py` writes the schema fields and the worked
example card, and rewrote the first-shape example (`card_contents`,
`card_cost`, `max_per_deck`, formation `deck_budget`) on 2026-10-29. Code:
`simulations/formation/deck_builder.py` (state) and `deck_builder_view.py`
(drawing); tests in `tests/test_formation_deck_builder.py`.

### Fielding: what a deck draws on (built 2026-10-29)

Owner decisions, 2026-10-29: fielding a card consumes manpower and equipment;
for now large services are single cumulative pops ("US Army service
members", "US Air Force airmen"), kept low effort; equipment comes from depots
that are sites with logistics routes attached, and carrying it creates
logistics demand; a copy that cannot be filled is fielded understrength. It
has to work for ground, naval, air and space formations alike.

Code: `simulations/formation/fielding.py`, called by the deck on `+`, `-` and
removal. Blueprint decks are plans and draw nothing.

- **Manpower.** A service pop (`pop_type: service`, `faction`,
  `population_count`) is one service's members. A formation draws on its
  `manpower_pop`, else the nearest ancestor's, else its faction's first
  service pop. Nothing is written to the pop: its free headcount is its
  `population_count` less the people every drawing deck on it holds. People
  are counted by role in `DeckBuilder.card_draw`, crew included.
- **Equipment.** A depot is a location with `site_class: depot`, a
  `controlling_factions` entry, `vehicle_stock` (`[{vehicle, quantity}]`) and
  `inventory_items` (`[{item, quantity, unit}]`). A formation draws on its
  `supply_depot` (or the nearest ancestor's) first, then on its faction's
  other depots. Stock leaves the depot when the copy is fielded.
- **Logistics demand.** Each depot a formation draws on gets one `logistics`
  entity, `log_supply_<formation>_from_<depot>`: `route_class: formation
  supply`, `status: requested`, `origin_location` the depot,
  `destination_location` the formation's `location` (inherited; blank when
  none is set), `requested_by` the formation and the cargo in
  `cargo_manifest` (`[{kind, vehicle|item, quantity}]`). The depot lists it in
  `outbound_logistics_routes`. This is the demand the logistics concept's
  coarse traffic is meant to read (docs/logistics_simulation_concept_v001.md
  section 3.4). Nothing carries it yet.
- **Understrength.** What a pool cannot give is stored on the deck row as
  `short` (`{"people": n, "vehicle:<id>": n, "item:<id>": n}`). Tiles show it
  in red and the header totals it. Removing a copy removes its shortfall
  first, so the weakest copy goes; then its people return to the pool and
  its equipment to the depot it came from, and that part of the demand is
  cancelled (`status: cancelled` once empty).
- **Every domain.** Depots can be any location: a ground site, a naval base,
  an orbital station. The demand names only its ends; the logistics domain
  follows from them. Vehicles without crew roles fall back to their
  `crew_complement` as one "Crew" role, so a Fletcher-class destroyer brings
  329 people. Aircraft and spacecraft have their own tile silhouettes.

Test data from `tools/author_unit_card_model.py` (placeholder figures):

- service pops: GGO Sol Marine service members (180,000), US Army service
  members (480,000), US Air Force airmen (330,000; the USAF formation draws
  on it) and US Navy sailors (340,000; the Navy formation draws on it);
- `site_ggo_luna_supply_depot` on Luna: 9 Test Tanks, 12 jeeps, 24 exosuits,
  one Test Spacecraft, 600 rifles and 80 machine guns;
- crew roles for T-64 (3), MiG-21 (1), Schuetzenpanzer Puma (3) and Tatra
  813 (1);
- cards: GGO Rifle Squad, Recon Patrol, Exosuit Section and Assault Carrier
  (from 2448, with the Tank Platoon), and unowned era cards: Fletcher-class
  Destroyer (1942-1971), MiG-21 Flight (1959-2105), T-64 Tank Platoon
  (1966-2034), D-48 Anti-Tank Gun Section with Tatra tow trucks (1967-2153),
  F-22 Raptor Pair (2005-2176) and Panzergrenadier Group with its Puma
  (2015-2131).

Not built yet: individual `vehicle_units` linked before counted stock;
anything delivering the demands; depots for the US services; locations for
the GGO formations (their deliveries have no destination yet). The crew of a
vehicle the depot could not give is still drawn.

### People: representatives and the crowd (built 2026-10-29)

The people a fielded deck holds stay a count drawn from the service pop
until someone looks. The Deck tab's `People` panel, right of the tiles,
lists them by role (card manpower roles and vehicle crew roles, command roles
first) with how many the deck holds and how many it is short. Under each
role come:

- the people saved as serving in the formation (`serves_in`), marked
  `saved`;
- up to three representatives: runtime people drawn from a seed
  (`<formation>:<role>:<n>`), so the same name, sex, age and birth
  personality come back every time. A pop's `representative_names` are used
  when it has them, otherwise placeholder name lists;
- "and N more", the crowd.

Clicking a name shows the person: sex, age, rank and role, source pop and the
one or two Big Five axes their birth leans on. `Save as person` on a
representative writes one person to the ontology at once (like the deck's
other edits): `birth_seed` (the representative's seed, so they stay who they
were), `genetic_dna`, `start_year`, `sex`, `person_class: service member`,
`serves_in`, `service_role`, `service_rank`, `source_pop` and
`affiliated_factions`. A saved person is one of the people the deck holds,
not one more; the representatives move on to the next seed. A saved person
offers `Open person` and `Person Editor`, which open the existing person
tabs.

What a pool could not give is taken from the roles that are not command
first, in proportion to what each needs; a blueprint holds nobody. Code:
`simulations/formation/formation_people.py`. `schema_person` gained
`serves_in`, `service_role`, `service_rank` and `source_pop` through
`tools/author_unit_card_model.py`.

Not built yet: names from a culture or era rather than one placeholder list;
showing a formation's people in Site Simulation or on the map; what happens
to a saved person when the deck stands down below them (they stay, shown
under their role).
