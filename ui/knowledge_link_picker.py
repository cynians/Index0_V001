import pygame

from ui.card_wiki import CardWikiRenderer
from ui.wiki_link_tools import (
    build_entity_link_matches,
    choose_link_target,
    find_link_seed,
    insert_wiki_link,
)


class KnowledgeLinkPickerMixin:
    def _known_entities_for_matching(self):
        loader = getattr(self.world_model, "loader", None) if self.world_model is not None else None
        entities = getattr(loader, "entities", None)
        if isinstance(entities, dict):
            return [entity for entity in entities.values() if isinstance(entity, dict)]
        return []

    def _entity_match_tokens(self, entity):
        tokens = []
        for value in (
            entity.get("id"),
            self._entity_display_label(entity, fallback=entity.get("id")),
            entity.get("pretty_name"),
            entity.get("name"),
            entity.get("common_name"),
            entity.get("binomial_name"),
        ):
            text = str(value or "").strip()
            if text and text.lower() not in tokens:
                tokens.append(text.lower())
        return tokens

    def _resolve_wiki_mention_ref(self, link_text):
        raw_text = str(link_text or "").strip()
        if not raw_text:
            return ""

        if self.world_model is not None:
            entity = self.world_model.get_entity(raw_text)
            if isinstance(entity, dict) and entity.get("id"):
                return str(entity["id"])

        normalized = raw_text.lower()
        for entity in self._known_entities_for_matching():
            if normalized in self._entity_match_tokens(entity):
                entity_id = entity.get("id")
                if entity_id:
                    return str(entity_id)
        return raw_text

    def _wiki_mentions_from_text(self, wiki_text):
        mentions = []
        seen = set()
        for link_text in CardWikiRenderer.extract_link_refs(wiki_text):
            mention = self._resolve_wiki_mention_ref(link_text)
            if not mention or mention in seen:
                continue
            seen.add(mention)
            mentions.append(mention)
        return mentions

    def _sync_card_wiki_mentions(self, card, wiki_text=None):
        entity = self._entity_for_card(card)
        if not isinstance(entity, dict):
            return False

        if wiki_text is None:
            if (
                card is not None
                and card.get("active_edit_field") == "wiki_entry"
                and "edit_buffer" in card
            ):
                wiki_text = card.get("edit_buffer", "")
            else:
                wiki_text = entity.get("wiki_entry", "")

        mentions = self._wiki_mentions_from_text(wiki_text)
        changed = False
        related = entity.get("related")
        if isinstance(related, list):
            related_values = [
                str(value).strip()
                for value in related
                if isinstance(value, str) and str(value).strip()
            ]
        elif related in (None, "", []):
            related_values = []
        else:
            related_values = [str(related).strip()]

        for legacy_field in ("derived_from", "wiki_mentions"):
            legacy_value = entity.pop(legacy_field, None)
            if legacy_value is None:
                continue
            changed = True
            if isinstance(legacy_value, list):
                legacy_values = legacy_value
            elif legacy_value in ("", []):
                legacy_values = []
            else:
                legacy_values = [legacy_value]
            for value in legacy_values:
                if not isinstance(value, str):
                    continue
                value = value.strip()
                if value and value not in related_values:
                    related_values.append(value)

        for mention in mentions:
            if mention not in related_values:
                related_values.append(mention)
                changed = True

        if entity.get("related") != related_values:
            entity["related"] = related_values
            changed = True
        return changed

    def _close_wiki_link_picker(self, card):
        card["wiki_link_picker_open"] = False
        card["wiki_link_query"] = ""
        card["wiki_link_matches"] = []
        card["wiki_link_selected_index"] = 0
        card["wiki_link_replace_range"] = None

    def _build_wiki_link_matches(self, query_text):
        if self.world_model is None:
            return []
        return build_entity_link_matches(
            self.world_model.loader.entities.values(),
            query_text,
            display_label=lambda entity, fallback: self._entity_display_label(
                entity,
                fallback=fallback,
            ),
            coerce_year=self._coerce_card_year,
        )

    def _open_wiki_link_picker(self, card):
        query_text, replace_start, replace_end = self._wiki_link_seed_from_cursor(card)
        card["wiki_link_picker_open"] = True
        card["wiki_link_query"] = query_text
        card["wiki_link_replace_range"] = (replace_start, replace_end)
        card["wiki_link_matches"] = self._build_wiki_link_matches(query_text)
        card["wiki_link_selected_index"] = 0

    def _wiki_link_seed_from_cursor(self, card):
        buffer_text = str(card.get("edit_buffer", ""))
        cursor = max(0, min(len(buffer_text), int(card.get("edit_cursor", len(buffer_text)))))
        return find_link_seed(buffer_text, cursor)

    def _insert_wiki_link_from_picker(self, card):
        link_target = choose_link_target(
            card.get("wiki_link_matches", []),
            card.get("wiki_link_selected_index", 0),
            card.get("wiki_link_query", ""),
        )
        if not link_target:
            return False

        current_buffer = str(card.get("edit_buffer", ""))
        cursor = max(0, min(len(current_buffer), int(card.get("edit_cursor", len(current_buffer)))))
        result = insert_wiki_link(
            current_buffer,
            link_target,
            replace_range=card.get("wiki_link_replace_range", (cursor, cursor)),
            cursor=cursor,
        )
        if result is None:
            return False

        card["edit_buffer"], card["edit_cursor"] = result
        card["last_edit_action"] = "draft"
        self._save_card_draft(card)
        self._close_wiki_link_picker(card)
        return True

    def _handle_wiki_link_picker_keydown(self, card, event):
        if not card.get("wiki_link_picker_open", False):
            return False

        if event.key == pygame.K_ESCAPE:
            self._close_wiki_link_picker(card)
            return True

        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            return self._insert_wiki_link_from_picker(card)

        matches = card.get("wiki_link_matches", [])
        if event.key == pygame.K_UP and matches:
            card["wiki_link_selected_index"] = max(
                0,
                card.get("wiki_link_selected_index", 0) - 1,
            )
            return True

        if event.key == pygame.K_DOWN and matches:
            card["wiki_link_selected_index"] = min(
                len(matches) - 1,
                card.get("wiki_link_selected_index", 0) + 1,
            )
            return True

        if event.key == pygame.K_BACKSPACE:
            card["wiki_link_query"] = card.get("wiki_link_query", "")[:-1]
            card["wiki_link_matches"] = self._build_wiki_link_matches(
                card["wiki_link_query"]
            )
            card["wiki_link_selected_index"] = 0
            return True

        text = getattr(event, "unicode", "")
        if text and text.isprintable():
            card["wiki_link_query"] = card.get("wiki_link_query", "") + text
            card["wiki_link_matches"] = self._build_wiki_link_matches(
                card["wiki_link_query"]
            )
            card["wiki_link_selected_index"] = 0
            return True

        return False
