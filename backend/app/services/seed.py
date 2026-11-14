"""Deterministic fake-data generator.

Same `seed` + same `anchor_date` -> byte-for-byte the same dataset. Dates are
generated backwards from the anchor (default: today), so the dashboard always
looks "live" while records stay reproducible.

On top of the random data, a few hand-written SCENARIOS are always created
first (so they get stable, low IDs). Each one is a realistic support case with
a known correct resolution, which makes them ideal test cases for AI agents.
"""

import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from faker import Faker
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError
from app.db import Base
from app.models import (
    Customer,
    CustomerTier,
    MessageAuthor,
    Order,
    OrderItem,
    OrderStatus,
    Product,
    ProductCategory,
    Refund,
    RefundReason,
    Ticket,
    TicketCategory,
    TicketMessage,
    TicketPriority,
    TicketStatus,
)

CATALOG: dict[ProductCategory, dict[str, list]] = {
    ProductCategory.electronics: {
        "adj": ["Wireless", "Noise-Cancelling", "Smart", "Portable", "Ultra-Slim", "Pro"],
        "noun": [
            "Headphones",
            "Earbuds",
            "Speaker",
            "Power Bank",
            "Keyboard",
            "Mouse",
            "Webcam",
            "Smartwatch",
            "USB-C Hub",
            "Monitor Light",
        ],
        "price": (1499, 24999),
    },
    ProductCategory.home: {
        "adj": ["Ceramic", "Bamboo", "Minimalist", "Insulated", "Stackable", "Linen"],
        "noun": [
            "Mug Set",
            "Cutting Board",
            "Desk Lamp",
            "Water Bottle",
            "Storage Bins",
            "Throw Blanket",
            "Plant Pot",
            "Coffee Grinder",
            "Wall Clock",
        ],
        "price": (999, 8999),
    },
    ProductCategory.apparel: {
        "adj": ["Organic Cotton", "Merino", "Waterproof", "Relaxed-Fit", "Classic", "Thermal"],
        "noun": [
            "T-Shirt",
            "Hoodie",
            "Rain Jacket",
            "Joggers",
            "Socks (3-pack)",
            "Cap",
            "Sweater",
            "Running Shorts",
        ],
        "price": (1299, 12999),
    },
    ProductCategory.books: {
        "adj": ["The Practical", "The Pocket", "Essential", "Modern", "Illustrated"],
        "noun": [
            "Guide to Python",
            "Cookbook",
            "Atlas",
            "Field Notes",
            "Book of Systems",
            "Handbook of Design",
            "Journal",
        ],
        "price": (899, 4999),
    },
    ProductCategory.sports: {
        "adj": ["Non-Slip", "Adjustable", "Lightweight", "Pro-Grip", "Foldable"],
        "noun": [
            "Yoga Mat",
            "Dumbbells",
            "Jump Rope",
            "Resistance Bands",
            "Foam Roller",
            "Gym Bag",
            "Cycling Gloves",
        ],
        "price": (999, 15999),
    },
    ProductCategory.beauty: {
        "adj": ["Hydrating", "Vitamin C", "Fragrance-Free", "Overnight", "Mineral"],
        "noun": ["Face Serum", "Moisturizer", "Sunscreen SPF 50", "Lip Balm", "Cleanser", "Hair Oil"],
        "price": (599, 5999),
    },
}

# (category, subject, first customer message, needs_order)
TICKET_TEMPLATES: list[tuple[TicketCategory, str, str, bool]] = [
    (
        TicketCategory.shipping,
        "Where is my order?",
        "Hi, I placed order {order} a while ago and haven't received it yet. Can you check?",
        True,
    ),
    (
        TicketCategory.shipping,
        "Wrong delivery address",
        "I think I entered the wrong address on {order}. Can it still be changed?",
        True,
    ),
    (
        TicketCategory.product,
        "Item arrived damaged",
        "The {product} in order {order} arrived damaged. The box was crushed.",
        True,
    ),
    (
        TicketCategory.product,
        "Received the wrong item",
        "I ordered {product} ({order}) but got something completely different.",
        True,
    ),
    (
        TicketCategory.product,
        "How do I use this?",
        "I bought {product} and I'm not sure how to set it up. Any guide?",
        True,
    ),
    (
        TicketCategory.billing,
        "Charged twice",
        "I see two charges on my card for order {order}. Please fix this.",
        True,
    ),
    (
        TicketCategory.billing,
        "Request a refund",
        "I'd like a refund for {order}, it isn't what I expected.",
        True,
    ),
    (TicketCategory.billing, "Invoice needed", "Could you send me a GST/VAT invoice for {order}?", True),
    (
        TicketCategory.account,
        "Can't log in",
        "I keep getting 'invalid password' even after resetting it.",
        False,
    ),
    (
        TicketCategory.account,
        "Update my email",
        "Please change my account email, I no longer use this one.",
        False,
    ),
    (
        TicketCategory.other,
        "Do you ship internationally?",
        "Do you ship to Singapore? What would delivery cost?",
        False,
    ),
    (
        TicketCategory.other,
        "Bulk order discount",
        "We want to order 50 units for our office. Is there a discount?",
        False,
    ),
]

AGENT_REPLIES = [
    "Thanks for reaching out! I'm looking into this now.",
    "Sorry about the trouble. Could you share a photo so we can process this faster?",
    "I've checked the order and escalated it to our logistics team.",
    "Thanks for your patience, this has now been resolved on our side.",
]

ASSIGNEES = ["asha", "ben", "chen", "dana", None]


@dataclass
class SeedCounts:
    customers: int = 60
    products: int = 40
    orders: int = 250
    tickets: int = 60


@dataclass
class SeedSummary:
    seed: int
    customers: int
    products: int
    orders: int
    tickets: int
    refunds: int
    scenarios: list[str]


def reset_database(db: Session) -> None:
    bind = db.get_bind()
    db.close()
    # Store data only: chat history isn't generated, so it survives a reseed.
    tables = [t for t in Base.metadata.sorted_tables if not t.name.startswith("chat_")]
    Base.metadata.drop_all(bind=bind, tables=tables)
    Base.metadata.create_all(bind=bind, tables=tables)


class _Gen:
    def __init__(self, db: Session, seed: int, anchor: datetime):
        self.db = db
        self.rng = random.Random(seed)
        self.fake = Faker("en_US")
        self.fake.seed_instance(seed)
        self.anchor = anchor
        self.order_seq = 0
        self.refund_count = 0

    # ----- helpers -----
    def ago(self, days: float, jitter_hours: int = 10) -> datetime:
        return self.anchor - timedelta(days=days, hours=self.rng.randint(0, jitter_hours))

    def next_number(self) -> str:
        self.order_seq += 1
        return f"ORD-{self.order_seq:08d}"

    def add_order(
        self,
        customer: Customer,
        lines: list[tuple[Product, int]],
        status: OrderStatus,
        placed_at: datetime,
    ) -> Order:
        order = Order(
            number=self.next_number(),
            customer=customer,
            status=status,
            currency="USD",
            shipping_address=f"{self.fake.street_address()}, {customer.city}, {customer.country}",
            placed_at=placed_at,
            created_at=placed_at,
            updated_at=placed_at,
        )
        for product, qty in lines:
            order.items.append(
                OrderItem(
                    product_id=product.id,
                    product_name=product.name,
                    unit_price_cents=product.price_cents,
                    quantity=qty,
                )
            )
        order.total_cents = sum(p.price_cents * q for p, q in lines)
        if status in (OrderStatus.shipped, OrderStatus.delivered, OrderStatus.refunded):
            order.shipped_at = placed_at + timedelta(days=self.rng.randint(1, 2))
            order.tracking_number = f"TRK{self.rng.randint(10**9, 10**10 - 1)}"
        if status in (OrderStatus.delivered, OrderStatus.refunded):
            order.delivered_at = order.shipped_at + timedelta(days=self.rng.randint(2, 6))
        self.db.add(order)
        return order

    def add_refund(self, order: Order, amount: int, reason: RefundReason, at: datetime, note=""):
        order.refunds.append(Refund(amount_cents=amount, reason=reason, note=note, created_at=at))
        self.refund_count += 1

    def add_ticket(
        self,
        customer: Customer,
        order: Order | None,
        *,
        subject: str,
        category: TicketCategory,
        priority: TicketPriority,
        status: TicketStatus,
        messages: list[tuple[MessageAuthor, str]],
        created_at: datetime,
        assignee: str | None = None,
    ) -> Ticket:
        t = Ticket(
            customer=customer,
            order=order,
            subject=subject,
            category=category,
            priority=priority,
            status=status,
            assignee=assignee,
            created_at=created_at,
            updated_at=created_at + timedelta(hours=len(messages) * 3),
        )
        for i, (author, body) in enumerate(messages):
            t.messages.append(
                TicketMessage(author=author, body=body, created_at=created_at + timedelta(hours=i * 3))
            )
        self.db.add(t)
        return t

    # ----- products -----
    def products(self, n: int) -> list[Product]:
        products: list[Product] = []
        seen: set[str] = set()
        cats = list(CATALOG)
        variants = ["Mini", "Max", "Lite", "Plus", "XL", "v2"]
        while len(products) < n:
            cat = cats[len(products) % len(cats)]
            spec = CATALOG[cat]
            name = f"{self.rng.choice(spec['adj'])} {self.rng.choice(spec['noun'])}"
            if name in seen:
                name = f"{name} {self.rng.choice(variants)}"
            if name in seen:
                # Word combinations ran out: number the edition so names stay unique
                # and the requested count is always met.
                base, edition = name, 2
                while (name := f"{base} (Edition {edition})") in seen:
                    edition += 1
            seen.add(name)
            lo, hi = spec["price"]
            price = self.rng.randrange(lo // 100 + 1, hi // 100 + 1) * 100 - 1  # e.g. 2499
            stock = self.rng.choice([0, 2, 4] + [self.rng.randint(10, 300)] * 6)
            p = Product(
                sku=f"{cat.value[:3].upper()}-{len(products) + 1:04d}",
                name=name,
                description=self.fake.sentence(nb_words=14),
                category=cat,
                price_cents=price,
                stock=stock,
                is_active=self.rng.random() > 0.05,
            )
            self.db.add(p)
            products.append(p)
        self.db.flush()
        return products

    # ----- customers -----
    def customers(self, n: int) -> list[Customer]:
        out: list[Customer] = []
        emails: set[str] = set()
        while len(out) < n:
            first, last = self.fake.first_name(), self.fake.last_name()
            email = f"{first}.{last}{self.rng.randint(1, 999)}@example.com".lower()
            if email in emails:
                continue
            emails.add(email)
            joined = self.ago(self.rng.randint(30, 720))
            c = Customer(
                name=f"{first} {last}",
                email=email,
                phone=self.fake.numerify("+1-###-###-####"),
                city=self.fake.city(),
                country=self.rng.choice(["USA", "USA", "USA", "Canada", "UK", "India"]),
                tier=self.rng.choices(
                    [CustomerTier.standard, CustomerTier.gold, CustomerTier.platinum],
                    weights=[75, 20, 5],
                )[0],
                created_at=joined,
                updated_at=joined,
            )
            self.db.add(c)
            out.append(c)
        self.db.flush()
        return out

    # ----- orders -----
    def orders(self, n: int, customers: list[Customer], products: list[Product]) -> list[Order]:
        sellable = [p for p in products if p.is_active] or products
        out = []
        for _ in range(n):
            customer = self.rng.choice(customers)
            age = self.rng.uniform(0, 180)
            placed = self.ago(age)
            if placed < customer.created_at:
                placed = customer.created_at + timedelta(hours=1)
            k = self.rng.choices([1, 2, 3, 4], weights=[50, 30, 15, 5])[0]
            picked = self.rng.sample(sellable, k=min(k, len(sellable)))
            lines = [(p, self.rng.choices([1, 2, 3], weights=[80, 15, 5])[0]) for p in picked]

            # Older orders are further along the lifecycle.
            if age < 2:
                status = self.rng.choice([OrderStatus.pending, OrderStatus.paid])
            elif age < 6:
                status = self.rng.choice([OrderStatus.paid, OrderStatus.shipped])
            elif age < 12:
                status = self.rng.choices([OrderStatus.shipped, OrderStatus.delivered], weights=[30, 70])[0]
            else:
                status = OrderStatus.delivered
            if self.rng.random() < 0.05:
                status = OrderStatus.cancelled

            order = self.add_order(customer, lines, status, placed)

            if status == OrderStatus.delivered and self.rng.random() < 0.08:
                full = self.rng.random() < 0.5
                amount = order.total_cents if full else max(order.total_cents // 3, 100)
                self.add_refund(
                    order,
                    amount,
                    self.rng.choice(list(RefundReason)),
                    order.delivered_at + timedelta(days=self.rng.randint(1, 5)),
                )
                if full:
                    order.status = OrderStatus.refunded
            out.append(order)
        self.db.flush()
        return out

    # ----- tickets -----
    def tickets(self, n: int, customers: list[Customer], orders: list[Order]) -> None:
        orders_by_customer: dict[int, list[Order]] = {}
        for o in orders:
            orders_by_customer.setdefault(o.customer_id, []).append(o)
        with_orders = [c for c in customers if c.id in orders_by_customer]

        for _ in range(n):
            category, subject, template, needs_order = self.rng.choice(TICKET_TEMPLATES)
            if needs_order and with_orders:
                customer = self.rng.choice(with_orders)
                order = self.rng.choice(orders_by_customer[customer.id])
                created = max(order.placed_at, self.ago(self.rng.uniform(0, 60)))
            else:
                customer, order = self.rng.choice(customers), None
                created = self.ago(self.rng.uniform(0, 60))
            if created > self.anchor:
                created = self.anchor - timedelta(hours=1)

            body = template.format(
                order=order.number if order else "",
                product=order.items[0].product_name if order and order.items else "the item",
            )
            status = self.rng.choices(list(TicketStatus), weights=[35, 15, 35, 15])[0]
            msgs = [(MessageAuthor.customer, body)]
            if status != TicketStatus.open or self.rng.random() < 0.4:
                msgs.append((MessageAuthor.agent, self.rng.choice(AGENT_REPLIES)))
            priority = self.rng.choices(list(TicketPriority), weights=[25, 45, 22, 8])[0]
            self.add_ticket(
                customer,
                order,
                subject=subject,
                category=category,
                priority=priority,
                status=status,
                messages=msgs,
                created_at=created,
                assignee=self.rng.choice(ASSIGNEES) if status != TicketStatus.open else None,
            )

    # ----- scenarios -----
    def scenarios(self) -> tuple[list[str], list[Customer], list[Product]]:
        """Fixed support cases with known 'correct' resolutions. Created first."""

        def cust(name, email, tier, city, country):
            c = Customer(
                name=name,
                email=email,
                tier=tier,
                city=city,
                country=country,
                phone="+1-555-010-0000",
                created_at=self.ago(400),
                updated_at=self.ago(400),
            )
            self.db.add(c)
            return c

        def prod(sku, name, cat, price, stock):
            p = Product(
                sku=sku,
                name=name,
                category=cat,
                price_cents=price,
                stock=stock,
                description=f"{name}. A ShopDesk best-seller.",
                is_active=True,
            )
            self.db.add(p)
            return p

        priya = cust("Priya Sharma", "priya.sharma@example.com", CustomerTier.gold, "Pune", "India")
        marcus = cust("Marcus Lee", "marcus.lee@example.com", CustomerTier.standard, "Austin", "USA")
        elena = cust("Elena Garcia", "elena.garcia@example.com", CustomerTier.platinum, "Madrid", "Spain")
        james = cust("James Okafor", "james.okafor@example.com", CustomerTier.standard, "Leeds", "UK")

        headphones = prod(
            "SCN-0001", "Aurora Noise-Cancelling Headphones", ProductCategory.electronics, 19999, 25
        )
        lamp = prod("SCN-0002", "Halo Desk Lamp", ProductCategory.home, 4999, 40)
        mat = prod("SCN-0003", "Grip Pro Yoga Mat", ProductCategory.sports, 3499, 0)  # out of stock
        serum = prod("SCN-0004", "Glow Vitamin C Serum", ProductCategory.beauty, 2499, 120)
        self.db.flush()

        # 1. Damaged item -> full refund of that item is the right call.
        o1 = self.add_order(priya, [(headphones, 1), (serum, 2)], OrderStatus.delivered, self.ago(9))
        self.add_ticket(
            priya,
            o1,
            subject="Headphones arrived with a cracked headband",
            category=TicketCategory.product,
            priority=TicketPriority.high,
            status=TicketStatus.open,
            created_at=self.ago(2),
            messages=[
                (
                    MessageAuthor.customer,
                    f"Hi, my Aurora headphones from order {o1.number} arrived with a cracked "
                    "headband. The serum was fine. I'd like a refund for the headphones please.",
                )
            ],
        )

        # 2. Late delivery -> shipped 12 days ago, never delivered.
        o2 = self.add_order(marcus, [(lamp, 1)], OrderStatus.shipped, self.ago(14))
        o2.shipped_at = self.ago(12)
        self.add_ticket(
            marcus,
            o2,
            subject="Still waiting for my lamp",
            category=TicketCategory.shipping,
            priority=TicketPriority.medium,
            status=TicketStatus.open,
            created_at=self.ago(1),
            messages=[
                (
                    MessageAuthor.customer,
                    f"Order {o2.number} shipped almost two weeks ago and tracking hasn't moved. Where is it?",
                )
            ],
        )

        # 3. Partial refund already issued -> agent must not refund more than what's left.
        o3 = self.add_order(elena, [(headphones, 1), (lamp, 1)], OrderStatus.delivered, self.ago(20))
        self.add_refund(o3, 4999, RefundReason.wrong_item, self.ago(15), note="Lamp refunded")
        self.add_ticket(
            elena,
            o3,
            subject="Want a full refund on everything",
            category=TicketCategory.billing,
            priority=TicketPriority.high,
            status=TicketStatus.open,
            created_at=self.ago(1),
            messages=[
                (
                    MessageAuthor.customer,
                    f"I want my whole order {o3.number} refunded, $249.98 back to my card.",
                )
            ],
        )

        # 4. Cancel request on a paid, not-yet-shipped order -> cancel is allowed.
        o4 = self.add_order(james, [(serum, 1), (lamp, 1)], OrderStatus.paid, self.ago(0.5, 2))
        self.add_ticket(
            james,
            o4,
            subject="Please cancel my order",
            category=TicketCategory.billing,
            priority=TicketPriority.medium,
            status=TicketStatus.open,
            created_at=self.ago(0.2, 1),
            messages=[
                (MessageAuthor.customer, f"I ordered by mistake, please cancel {o4.number} before it ships.")
            ],
        )

        # 5. Asking about an out-of-stock product.
        self.add_ticket(
            james,
            None,
            subject="When is the yoga mat back?",
            category=TicketCategory.other,
            priority=TicketPriority.low,
            status=TicketStatus.open,
            created_at=self.ago(3),
            messages=[
                (
                    MessageAuthor.customer,
                    "The Grip Pro Yoga Mat shows sold out. When will it be back in stock?",
                )
            ],
        )

        self.db.flush()
        names = [
            f"damaged_item: priya.sharma@example.com, {o1.number} (delivered) -> refund headphones $199.99",
            f"late_delivery: marcus.lee@example.com, {o2.number} (shipped 12 days ago, not delivered)",
            f"partial_refund_limit: elena.garcia@example.com, {o3.number} -> only $199.99 left to refund",
            f"cancel_request: james.okafor@example.com, {o4.number} (paid, not shipped) -> cancel",
            "out_of_stock_question: james.okafor@example.com asks about SCN-0003 (stock 0)",
        ]
        return names, [priya, marcus, elena, james], [headphones, lamp, mat, serum]


def seed_database(
    db: Session,
    *,
    seed: int = 42,
    counts: SeedCounts | None = None,
    reset: bool = True,
    anchor_date: date | None = None,
) -> SeedSummary:
    counts = counts or SeedCounts()
    if reset:
        reset_database(db)
    elif not is_empty(db):
        raise ConflictError(
            "Database already has data. Seeding is only supported into an empty database.",
            details={"hint": "Send reset=true to wipe and regenerate."},
        )

    anchor_day = anchor_date or datetime.now(UTC).date()
    anchor = datetime.combine(anchor_day, time(hour=12), tzinfo=UTC)
    gen = _Gen(db, seed, anchor)

    scenario_names, scenario_customers, scenario_products = gen.scenarios()
    products = gen.products(counts.products)
    customers = gen.customers(counts.customers)
    orders = gen.orders(counts.orders, customers + scenario_customers, products)
    gen.tickets(counts.tickets, customers, orders)
    db.commit()

    def count(model) -> int:
        return db.scalar(select(func.count()).select_from(model)) or 0

    # Report what's actually in the database, not what was requested.
    return SeedSummary(
        seed=seed,
        customers=count(Customer),
        products=count(Product),
        orders=count(Order),
        tickets=count(Ticket),
        refunds=gen.refund_count,
        scenarios=scenario_names,
    )


def is_empty(db: Session) -> bool:
    return db.query(Customer.id).first() is None
