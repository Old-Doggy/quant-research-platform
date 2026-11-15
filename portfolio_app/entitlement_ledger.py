"""Registration holdings, dividend receivables and cash settlement."""
from .corporate_actions import CorporateActionError, normalize_actions
import math


class EntitlementBook:
    def __init__(self, actions=()):
        self.actions = normalize_actions(actions)
        self.registered = {}
        self.accrued = set()
        self.paid = set()
        self.receivables = {}
        self.income_by_symbol = {}
        self.income_by_leg = {}
        self.events = []
        self._session = None
        self.share_locks = []

    def locked_quantities(self, session):
        result = {}
        for symbol, quantity, listing_date in self.share_locks:
            if session < listing_date:
                result[symbol] = result.get(symbol, 0) + quantity
        return result

    def _apply_shares(self, action, session, positions, lots):
        """Compute every leg before mutation; no implicit rounding or cash-in-lieu."""
        if self.locked_quantities(session).get(action.symbol, 0):
            raise CorporateActionError('未上市股份与新股份事件重叠，需先核对权益变更')
        _, registered_legs = self.registered[action.action_id]
        updates, total_added = [], 0
        for leg, registered in registered_legs.items():
            current_lots = [lot for lot in lots.get(leg, []) if lot['symbol'] == action.symbol and lot['quantity'] > 0]
            current = sum(lot['quantity'] for lot in current_lots)
            base = registered if action.action_type == 'bonus_share' else current
            added_float = base * (action.share_multiplier - 1)
            added = round(added_float)
            if not math.isclose(added_float, added, abs_tol=1e-8, rel_tol=0):
                raise CorporateActionError('零碎股结算尚未实现，不能自动取整')
            quantity = current + added
            cost = sum(lot['quantity'] * lot['price'] for lot in current_lots)
            if quantity < 0 or (quantity == 0 and cost):
                raise CorporateActionError('股份变更后的成本无法分配')
            updates.append((leg, quantity, cost / quantity if quantity else 0.))
            total_added += added
        for leg, quantity, price in updates:
            # Share reorganization pools this leg's basis; no FIFO tax claim is made.
            lots[leg] = [lot for lot in lots.get(leg, []) if lot['symbol'] != action.symbol]
            if quantity:
                lots[leg].append(dict(symbol=action.symbol, quantity=quantity, price=price))
        positions[action.symbol] = positions.get(action.symbol, 0) + total_added
        if action.listing_date > session:
            locked = total_added if action.action_type == 'bonus_share' else positions[action.symbol]
            if locked:
                self.share_locks.append((action.symbol, locked, action.listing_date))
        self.events.append(dict(action_id=action.action_id, session=session, kind='share_adjustment',
            symbol=action.symbol, quantity_delta=total_added, listing_date=action.listing_date,
            share_multiplier=action.share_multiplier, source=action.source, supersedes=action.supersedes))

    def _advance(self, session):
        if self._session is not None and session < self._session:
            raise CorporateActionError('公司行为处理日期不能倒退')
        self._session = session

    @property
    def receivable(self):
        return sum(self.receivables.values())

    def record_close(self, session, positions, lots):
        self._advance(session)
        for action in self.actions:
            if action.record_date != session or action.action_id in self.registered:
                continue
            quantity = positions.get(action.symbol, 0)
            legs = {leg: sum(lot['quantity'] for lot in items if lot['symbol'] == action.symbol)
                    for leg, items in lots.items()}
            if (isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0
                    or any(isinstance(q, bool) or not isinstance(q, int) or q < 0 for q in legs.values())
                    or sum(legs.values()) != quantity):
                raise CorporateActionError('登记日策略腿数量与证券持仓不一致')
            self.registered[action.action_id] = (quantity, legs)

    def open_session(self, session, positions, lots):
        self._advance(session)
        credit = 0.
        for action in self.actions:
            identity = action.action_id
            if action.ex_date > session:
                continue
            if identity not in self.registered:
                raise CorporateActionError('缺少公司行为登记日持仓；请扩大研究区间或提供期初权益')
            if action.action_type != 'cash_dividend':
                if identity not in self.accrued:
                    self._apply_shares(action, session, positions, lots)
                    self.accrued.add(identity)
                continue
            if identity not in self.accrued:
                quantity, legs = self.registered[identity]
                amount = quantity * action.cash_per_share
                self.receivables[identity] = amount
                self.income_by_symbol[action.symbol] = self.income_by_symbol.get(action.symbol, 0.) + amount
                for leg, qty in legs.items():
                    self.income_by_leg[leg] = self.income_by_leg.get(leg, 0.) + qty * action.cash_per_share
                self.accrued.add(identity)
                self.events.append(dict(action_id=identity, session=session, kind='receivable', amount=amount,
                                        symbol=action.symbol, source=action.source, tax_basis=action.tax_basis))
            if action.pay_date <= session and identity not in self.paid:
                amount = self.receivables.pop(identity)
                credit += amount
                self.paid.add(identity)
                self.events.append(dict(action_id=identity, session=session, kind='payment', amount=amount,
                                        symbol=action.symbol, source=action.source, tax_basis=action.tax_basis))
        return credit
