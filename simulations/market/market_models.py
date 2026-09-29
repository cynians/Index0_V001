"""Dependency-free runtime records for the market system.

These models describe changing simulation state, not ontology entities.  They
are intentionally independent of Pygame, ``WorldModel``, persistence, and
logistics execution so the market rules can be tested before integration.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, ClassVar


REPRESENTATION_MODES = frozenset({"aggregate", "corporal"})
ALLOCATION_STATUSES = frozenset(
    {"available", "partial", "reserved", "rationed", "redirected", "restricted", "unavailable"}
)
TRANSACTION_STATUSES = frozenset(
    {"proposed", "reserved", "awaiting_logistics", "in_transit", "delivered", "failed", "cancelled"}
)
FLOW_STATUSES = frozenset({"planned", "in_transit", "delivered", "lost", "cancelled"})


def _required_id(value: Any, field_name: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(f"{field_name} must be a non-empty identifier")
    return result


def _non_negative(value: Any, field_name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric") from exc
    if result < 0:
        raise ValueError(f"{field_name} cannot be negative")
    return result


def _optional_non_negative(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    return _non_negative(value, field_name)


def _representation(mode: Any, weight: Any) -> tuple[str, float]:
    normalized = str(mode or "aggregate").strip().lower()
    if normalized not in REPRESENTATION_MODES:
        raise ValueError(f"representation_mode must be one of {sorted(REPRESENTATION_MODES)}")
    return normalized, _non_negative(weight, "representative_weight")


def _copy_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _copy_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


class _RuntimeRecord:
    """Shared validation/serialization behavior for market runtime records."""

    _id_field: ClassVar[str] = "id"

    def __post_init__(self) -> None:
        if hasattr(self, self._id_field):
            identifier = _required_id(getattr(self, self._id_field), self._id_field)
            setattr(self, self._id_field, identifier)
        self.representation_mode, self.representative_weight = _representation(
            getattr(self, "representation_mode", "aggregate"),
            getattr(self, "representative_weight", 1.0),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SupplySnapshot(_RuntimeRecord):
    """Supply visible to one market at one point in time."""

    market_id: str
    commodity_id: str
    available_quantity: float
    unit: str = "unit"
    reserved_quantity: float = 0.0
    quality: float | None = None
    source_kind: str = "aggregate"
    source_id: str | None = None
    confidence: float = 1.0
    year: int | None = None
    representation_mode: str = "aggregate"
    representative_weight: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.market_id = _required_id(self.market_id, "market_id")
        self.commodity_id = _required_id(self.commodity_id, "commodity_id")
        self.available_quantity = _non_negative(self.available_quantity, "available_quantity")
        self.reserved_quantity = _non_negative(self.reserved_quantity, "reserved_quantity")
        if self.reserved_quantity > self.available_quantity:
            raise ValueError("reserved_quantity cannot exceed available_quantity")
        self.quality = _optional_non_negative(self.quality, "quality")
        self.confidence = _non_negative(self.confidence, "confidence")
        super().__post_init__()

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SupplySnapshot":
        return cls(**_copy_mapping(value))


@dataclass
class DemandRecord(_RuntimeRecord):
    """Explicit or inferred demand for a commodity."""

    id: str
    market_id: str
    commodity_id: str
    requested_quantity: float
    unit: str = "unit"
    consumer_kind: str | None = None
    consumer_id: str | None = None
    explicit: bool = False
    urgency: float = 0.0
    priority_profile: dict[str, Any] = field(default_factory=dict)
    destination_location_id: str | None = None
    status: str = "open"
    year: int | None = None
    representation_mode: str = "aggregate"
    representative_weight: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.market_id = _required_id(self.market_id, "market_id")
        self.commodity_id = _required_id(self.commodity_id, "commodity_id")
        self.requested_quantity = _non_negative(self.requested_quantity, "requested_quantity")
        self.urgency = _non_negative(self.urgency, "urgency")
        self.priority_profile = _copy_mapping(self.priority_profile)
        super().__post_init__()

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DemandRecord":
        return cls(**_copy_mapping(value))


@dataclass
class Offer(_RuntimeRecord):
    """A seller-specific or aggregate offer exposed by a market."""

    id: str
    market_id: str
    commodity_id: str
    quantity: float
    unit: str = "unit"
    seller_kind: str | None = None
    seller_id: str | None = None
    unit_price: float | None = None
    currency_id: str | None = None
    quality: float | None = None
    reserved_quantity: float = 0.0
    restrictions: list[str] = field(default_factory=list)
    expires_year: int | None = None
    representation_mode: str = "aggregate"
    representative_weight: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.market_id = _required_id(self.market_id, "market_id")
        self.commodity_id = _required_id(self.commodity_id, "commodity_id")
        self.quantity = _non_negative(self.quantity, "quantity")
        self.reserved_quantity = _non_negative(self.reserved_quantity, "reserved_quantity")
        if self.reserved_quantity > self.quantity:
            raise ValueError("reserved_quantity cannot exceed quantity")
        self.unit_price = _optional_non_negative(self.unit_price, "unit_price")
        self.quality = _optional_non_negative(self.quality, "quality")
        self.restrictions = [str(item) for item in _copy_list(self.restrictions)]
        if self.unit_price is not None and not str(self.currency_id or "").strip():
            raise ValueError("currency_id is required when unit_price is present")
        super().__post_init__()

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Offer":
        return cls(**_copy_mapping(value))


@dataclass
class ProcurementRequest(_RuntimeRecord):
    """A request to find and acquire supply through the market network."""

    id: str
    demand_id: str
    commodity_id: str
    origin_market_id: str
    requested_quantity: float
    unit: str = "unit"
    buyer_kind: str | None = None
    buyer_id: str | None = None
    urgency: float = 0.0
    max_transport_cost: float | None = None
    max_delivery_time: float | None = None
    search_levels: list[str] = field(default_factory=list)
    status: str = "open"
    year: int | None = None
    representation_mode: str = "aggregate"
    representative_weight: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.demand_id = _required_id(self.demand_id, "demand_id")
        self.commodity_id = _required_id(self.commodity_id, "commodity_id")
        self.origin_market_id = _required_id(self.origin_market_id, "origin_market_id")
        self.requested_quantity = _non_negative(self.requested_quantity, "requested_quantity")
        self.urgency = _non_negative(self.urgency, "urgency")
        self.max_transport_cost = _optional_non_negative(self.max_transport_cost, "max_transport_cost")
        self.max_delivery_time = _optional_non_negative(self.max_delivery_time, "max_delivery_time")
        self.search_levels = [str(item) for item in _copy_list(self.search_levels)]
        super().__post_init__()

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ProcurementRequest":
        return cls(**_copy_mapping(value))


@dataclass
class AllocationResult(_RuntimeRecord):
    """The result of applying scarcity and allocation policy to a request."""

    id: str
    request_id: str
    market_id: str
    commodity_id: str
    requested_quantity: float
    allocated_quantity: float
    unallocated_quantity: float
    status: str = "available"
    reason: str = ""
    allocation_policy: str = "open_supply"
    offer_ids: list[str] = field(default_factory=list)
    representation_mode: str = "aggregate"
    representative_weight: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.request_id = _required_id(self.request_id, "request_id")
        self.market_id = _required_id(self.market_id, "market_id")
        self.commodity_id = _required_id(self.commodity_id, "commodity_id")
        self.requested_quantity = _non_negative(self.requested_quantity, "requested_quantity")
        self.allocated_quantity = _non_negative(self.allocated_quantity, "allocated_quantity")
        self.unallocated_quantity = _non_negative(self.unallocated_quantity, "unallocated_quantity")
        if abs((self.allocated_quantity + self.unallocated_quantity) - self.requested_quantity) > 1e-9:
            raise ValueError("allocated_quantity plus unallocated_quantity must equal requested_quantity")
        if self.status not in ALLOCATION_STATUSES:
            raise ValueError(f"status must be one of {sorted(ALLOCATION_STATUSES)}")
        self.offer_ids = [str(item) for item in _copy_list(self.offer_ids)]
        super().__post_init__()

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AllocationResult":
        return cls(**_copy_mapping(value))


@dataclass
class Transaction(_RuntimeRecord):
    """A market commitment; it does not imply physical delivery."""

    id: str
    source_market_id: str
    destination_market_id: str
    commodity_id: str
    quantity: float
    unit: str = "unit"
    buyer_kind: str | None = None
    buyer_id: str | None = None
    seller_kind: str | None = None
    seller_id: str | None = None
    unit_price: float | None = None
    total_price: float | None = None
    currency_id: str | None = None
    status: str = "proposed"
    logistics_requirement_id: str | None = None
    year: int | None = None
    representation_mode: str = "aggregate"
    representative_weight: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.source_market_id = _required_id(self.source_market_id, "source_market_id")
        self.destination_market_id = _required_id(self.destination_market_id, "destination_market_id")
        self.commodity_id = _required_id(self.commodity_id, "commodity_id")
        self.quantity = _non_negative(self.quantity, "quantity")
        self.unit_price = _optional_non_negative(self.unit_price, "unit_price")
        self.total_price = _optional_non_negative(self.total_price, "total_price")
        if (self.unit_price is not None or self.total_price is not None) and not str(self.currency_id or "").strip():
            raise ValueError("currency_id is required when transaction pricing is present")
        if self.status not in TRANSACTION_STATUSES:
            raise ValueError(f"status must be one of {sorted(TRANSACTION_STATUSES)}")
        super().__post_init__()

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Transaction":
        return cls(**_copy_mapping(value))


@dataclass
class MarketFlow(_RuntimeRecord):
    """An aggregate or corporal movement associated with a transaction."""

    id: str
    source_market_id: str
    destination_market_id: str
    commodity_id: str
    quantity: float
    unit: str = "unit"
    status: str = "planned"
    flow_type: str = "trade"
    transaction_id: str | None = None
    logistics_requirement_id: str | None = None
    year: int | None = None
    representation_mode: str = "aggregate"
    representative_weight: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.source_market_id = _required_id(self.source_market_id, "source_market_id")
        self.destination_market_id = _required_id(self.destination_market_id, "destination_market_id")
        self.commodity_id = _required_id(self.commodity_id, "commodity_id")
        self.quantity = _non_negative(self.quantity, "quantity")
        if self.status not in FLOW_STATUSES:
            raise ValueError(f"status must be one of {sorted(FLOW_STATUSES)}")
        super().__post_init__()

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MarketFlow":
        return cls(**_copy_mapping(value))


@dataclass
class MarketState:
    """Changing state for one market scope at one simulation point."""

    market_id: str
    scope_kind: str = "local"
    year: int | None = None
    currency_id: str | None = None
    supply: list[SupplySnapshot] = field(default_factory=list)
    demand: list[DemandRecord] = field(default_factory=list)
    offers: list[Offer] = field(default_factory=list)
    allocations: list[AllocationResult] = field(default_factory=list)
    transactions: list[Transaction] = field(default_factory=list)
    flows: list[MarketFlow] = field(default_factory=list)
    prices: dict[str, float | list[float]] = field(default_factory=dict)
    shortages: dict[str, float] = field(default_factory=dict)
    reservations: dict[str, float] = field(default_factory=dict)
    price_history: list[dict[str, Any]] = field(default_factory=list)
    reconciliation: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.market_id = _required_id(self.market_id, "market_id")
        self.supply = [item if isinstance(item, SupplySnapshot) else SupplySnapshot.from_dict(item) for item in self.supply]
        self.demand = [item if isinstance(item, DemandRecord) else DemandRecord.from_dict(item) for item in self.demand]
        self.offers = [item if isinstance(item, Offer) else Offer.from_dict(item) for item in self.offers]
        self.allocations = [
            item if isinstance(item, AllocationResult) else AllocationResult.from_dict(item)
            for item in self.allocations
        ]
        self.transactions = [item if isinstance(item, Transaction) else Transaction.from_dict(item) for item in self.transactions]
        self.flows = [item if isinstance(item, MarketFlow) else MarketFlow.from_dict(item) for item in self.flows]
        self.prices = _copy_mapping(self.prices)
        self.shortages = {str(key): _non_negative(value, f"shortages[{key}]") for key, value in self.shortages.items()}
        self.reservations = {str(key): _non_negative(value, f"reservations[{key}]") for key, value in self.reservations.items()}
        self.price_history = [_copy_mapping(item) for item in self.price_history]
        self.reconciliation = _copy_mapping(self.reconciliation)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MarketState":
        return cls(**_copy_mapping(value))


def validate_runtime_record(record: Any) -> None:
    """Validate a supported record without coupling callers to its class."""

    if not is_dataclass(record):
        raise TypeError("record must be a market runtime dataclass")
    record.__post_init__()
