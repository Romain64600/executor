"""Data contracts for executor stage I/O — stdlib only, fail-closed.

Sprint 2's read-only extractor emits two artifacts:

- a :class:`RawSnapshot` — the feed as fetched (verbatim ``data-offer`` dicts,
  already ``html.unescape``-d and ``json.loads``-ed), plus run metadata;
- a :class:`NormalizedFeed` — typed, deduped :class:`NormalizedOffer` rows.

These dataclasses are the single source of truth for those JSON shapes, so a
stage's "≥0 offers extracted" success predicate (see EXECUTOR_RULES §2/§3) has
something concrete to validate against. Malformed input raises
:class:`ContractError` — never a silent pass. No third-party dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable


class ContractError(ValueError):
    """Raised when data does not satisfy a contract. Fail-closed."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _clean_str(value: Any) -> str | None:
    """Return a non-empty stripped string, or None."""

    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass(frozen=True)
class NormalizedOffer:
    """One typed offer row extracted from the WP merchant feed.

    ``offer_id``, ``name`` and ``url`` are mandatory. ``url`` must be a real
    http(s) URL from the feed — never invented or a placeholder (skill rule:
    "JAMAIS INVENTER D'URL").
    """

    offer_id: str
    name: str
    url: str
    merchant: str
    store_id: str | None = None
    price: str | None = None
    stock: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "offer_id": self.offer_id,
            "name": self.name,
            "url": self.url,
            "merchant": self.merchant,
            "store_id": self.store_id,
            "price": self.price,
            "stock": self.stock,
        }

    @classmethod
    def from_raw(cls, raw: dict[str, Any], *, merchant: str) -> "NormalizedOffer":
        _require(isinstance(raw, dict), "raw offer must be a dict")
        _require(bool(_clean_str(merchant)), "merchant is required")

        offer_id = _clean_str(raw.get("id"))
        name = _clean_str(raw.get("name"))
        url = _clean_str(raw.get("url"))
        _require(offer_id is not None, "raw offer missing 'id'")
        _require(name is not None, "raw offer missing 'name'")
        _require(url is not None, "raw offer missing 'url'")
        _require(
            url.startswith("http://") or url.startswith("https://"),
            f"offer url is not an http(s) URL: {url!r}",
        )

        return cls(
            offer_id=offer_id,
            name=name,
            url=url,
            merchant=merchant.strip(),
            store_id=_clean_str(raw.get("storeId")),
            price=_clean_str(raw.get("price")),
            stock=_clean_str(raw.get("stock")),
        )


@dataclass(frozen=True)
class RawSnapshot:
    """The feed as fetched, plus run metadata. Immutable audit artifact."""

    run_id: str
    merchant: str
    store_id: str
    source_url: str
    fetched_at: str
    pages_scanned: int
    raw_offers: tuple[dict[str, Any], ...]
    # The feed's OWN advertised page count (pagination nav / nav_max), distinct
    # from pages_scanned (a slice fetches 1 page of a 357-page feed). 0 = not
    # recorded. The submitter uses it to auto-default --max-pages so a big feed
    # (Difmark) doesn't abort the coverage scan at the 40-page floor (2026-07-20).
    feed_last_page: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "merchant": self.merchant,
            "store_id": self.store_id,
            "source_url": self.source_url,
            "fetched_at": self.fetched_at,
            "pages_scanned": self.pages_scanned,
            "feed_last_page": self.feed_last_page,
            "offer_count": len(self.raw_offers),
            "raw_offers": list(self.raw_offers),
        }

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        merchant: str,
        store_id: str | int,
        source_url: str,
        raw_offers: Iterable[dict[str, Any]],
        pages_scanned: int,
        feed_last_page: int = 0,
        clock: Callable[[], str] = _utc_now_iso,
    ) -> "RawSnapshot":
        _require(bool(_clean_str(run_id)), "run_id is required")
        _require(bool(_clean_str(merchant)), "merchant is required")
        _require(
            source_url.startswith("http://") or source_url.startswith("https://"),
            "source_url must be an http(s) URL",
        )
        _require(int(pages_scanned) >= 1, "pages_scanned must be >= 1")
        offers = tuple(raw_offers)
        _require(all(isinstance(o, dict) for o in offers), "every raw offer must be a dict")
        return cls(
            run_id=run_id.strip(),
            merchant=merchant.strip(),
            store_id=str(store_id),
            source_url=source_url,
            fetched_at=clock(),
            pages_scanned=int(pages_scanned),
            raw_offers=offers,
            feed_last_page=max(0, int(feed_last_page)),
        )


@dataclass(frozen=True)
class NormalizedFeed:
    """Typed, deduped offers derived from a :class:`RawSnapshot`."""

    run_id: str
    merchant: str
    fetched_at: str
    offers: tuple[NormalizedOffer, ...]
    feed_last_page: int = 0  # the feed's own advertised page count (see RawSnapshot)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "merchant": self.merchant,
            "fetched_at": self.fetched_at,
            "feed_last_page": self.feed_last_page,
            "offer_count": len(self.offers),
            "offers": [o.to_dict() for o in self.offers],
        }

    @classmethod
    def from_snapshot(cls, snapshot: RawSnapshot) -> "NormalizedFeed":
        """Normalize + dedupe by offer id across pages (skill rule F03b).

        Raises ContractError on the first malformed offer (fail-closed: a missing
        id/name/url is a parsing bug to fix, not to hide).
        """

        seen: set[str] = set()
        offers: list[NormalizedOffer] = []
        for raw in snapshot.raw_offers:
            offer = NormalizedOffer.from_raw(raw, merchant=snapshot.merchant)
            if offer.offer_id in seen:
                continue
            seen.add(offer.offer_id)
            offers.append(offer)
        return cls(
            run_id=snapshot.run_id,
            merchant=snapshot.merchant,
            fetched_at=snapshot.fetched_at,
            offers=tuple(offers),
            feed_last_page=snapshot.feed_last_page,
        )
