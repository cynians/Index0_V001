import unittest

from simulations.market import (
    AllocationResult,
    DemandRecord,
    MarketFlow,
    MarketState,
    Offer,
    ProcurementRequest,
    SupplySnapshot,
    Transaction,
)


class MarketRuntimeModelTests(unittest.TestCase):
    def test_records_round_trip_to_repository_compatible_dicts(self):
        demand = DemandRecord(
            id="demand_brewery_grain",
            market_id="market_city",
            commodity_id="item_grain",
            requested_quantity=20,
            consumer_kind="producer",
            consumer_id="producer_brewery",
            explicit=True,
            priority_profile={"reliability": 0.8, "urgency": 0.2},
            representation_mode="corporal",
            representative_weight=1.0,
        )
        restored = DemandRecord.from_dict(demand.to_dict())

        self.assertEqual(demand.to_dict(), restored.to_dict())
        self.assertEqual("producer_brewery", restored.consumer_id)
        self.assertTrue(restored.explicit)

    def test_market_state_accepts_nested_dicts_and_preserves_market_local_prices(self):
        state = MarketState.from_dict(
            {
                "market_id": "market_city",
                "scope_kind": "city",
                "year": 2400,
                "currency_id": "currency_credit",
                "supply": [
                    {
                        "market_id": "market_city",
                        "commodity_id": "item_grain",
                        "available_quantity": 100,
                        "reserved_quantity": 60,
                    }
                ],
                "prices": {"item_grain": 12.0},
            }
        )

        self.assertIsInstance(state.supply[0], SupplySnapshot)
        self.assertEqual(12.0, state.prices["item_grain"])
        self.assertEqual("market_city", state.to_dict()["market_id"])

    def test_scarcity_is_explicit_in_allocation_result(self):
        result = AllocationResult(
            id="allocation_001",
            request_id="procurement_001",
            market_id="market_city",
            commodity_id="item_steel",
            requested_quantity=2000,
            allocated_quantity=750,
            unallocated_quantity=1250,
            status="partial",
            reason="remaining supply is reserved",
            allocation_policy="contract_then_open_supply",
        )

        self.assertEqual(2000, result.requested_quantity)
        self.assertEqual(1250, result.unallocated_quantity)
        self.assertEqual("partial", result.status)

    def test_transaction_does_not_imply_physical_delivery(self):
        transaction = Transaction(
            id="transaction_001",
            source_market_id="market_regional",
            destination_market_id="market_city",
            commodity_id="item_steel",
            quantity=20,
            unit_price=18,
            currency_id="currency_credit",
            status="awaiting_logistics",
        )

        self.assertEqual("awaiting_logistics", transaction.status)
        self.assertIsNone(transaction.logistics_requirement_id)

    def test_offer_requires_currency_for_a_price(self):
        with self.assertRaisesRegex(ValueError, "currency_id is required"):
            Offer(
                id="offer_bad_currency",
                market_id="market_city",
                commodity_id="item_grain",
                quantity=5,
                unit_price=12,
            )

    def test_supply_and_offer_cannot_reserve_more_than_available(self):
        with self.assertRaisesRegex(ValueError, "reserved_quantity cannot exceed"):
            SupplySnapshot(
                market_id="market_city",
                commodity_id="item_grain",
                available_quantity=10,
                reserved_quantity=11,
            )

        with self.assertRaisesRegex(ValueError, "reserved_quantity cannot exceed"):
            Offer(
                id="offer_over_reserved",
                market_id="market_city",
                commodity_id="item_grain",
                quantity=10,
                reserved_quantity=11,
            )

    def test_negative_quantities_and_invalid_representation_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "cannot be negative"):
            ProcurementRequest(
                id="procurement_bad_quantity",
                demand_id="demand_001",
                commodity_id="item_grain",
                origin_market_id="market_city",
                requested_quantity=-1,
            )

        with self.assertRaisesRegex(ValueError, "representation_mode"):
            MarketFlow(
                id="flow_bad_mode",
                source_market_id="market_city",
                destination_market_id="market_region",
                commodity_id="item_grain",
                quantity=1,
                representation_mode="hybrid",
            )

    def test_flow_and_transaction_keep_aggregate_weight_explicit(self):
        flow = MarketFlow(
            id="flow_representative_trucks",
            source_market_id="market_region",
            destination_market_id="market_city",
            commodity_id="item_steel",
            quantity=500,
            representation_mode="corporal",
            representative_weight=150,
        )
        transaction = Transaction(
            id="transaction_representative_truck",
            source_market_id="market_region",
            destination_market_id="market_city",
            commodity_id="item_steel",
            quantity=500,
            status="in_transit",
            representation_mode="corporal",
            representative_weight=150,
        )

        self.assertEqual(150, flow.representative_weight)
        self.assertEqual(150, transaction.representative_weight)
        self.assertEqual("corporal", flow.representation_mode)


if __name__ == "__main__":
    unittest.main()
