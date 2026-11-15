"""Registration holdings, dividend receivables and cash settlement."""
from .corporate_actions import CorporateActionError, normalize_actions


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
