import pytest

from datetime import datetime

from d3a.models.market import Offer, Trade
from d3a.models.strategy.inter_area import InterAreaAgent


class FakeArea:
    def __init__(self, name):
        self.name = name
        self.current_tick = 10


class FakeMarket:
    def __init__(self, sorted_offers):
        self.sorted_offers = sorted_offers
        self.offer_count = 0

    @property
    def offers(self):
        return {offer.id: offer for offer in self.sorted_offers}

    @property
    def time_slot(self):
        return datetime.now()

    def accept_offer(self, *args):
        pass

    def delete_offer(self, *args):
        pass

    def offer(self, price, energy, seller):
        self.offer_count += 1
        self.forwarded_offer = Offer('fwd', price, energy, seller, market=self)
        return self.forwarded_offer


@pytest.fixture
def iaa():
    lower_market = FakeMarket([Offer('id', 1, 1, 'other')])
    higher_market = FakeMarket([Offer('id2', 3, 3, 'owner'), Offer('id3', 0.5, 1, 'owner')])
    owner = FakeArea('owner')
    iaa = InterAreaAgent(owner=owner, higher_market=higher_market, lower_market=lower_market)
    iaa.event_tick(area=iaa.owner)
    iaa.owner.current_tick = 14
    iaa.event_tick(area=iaa.owner)
    return iaa


def test_iaa_forwards_offers(iaa):
    assert iaa.lower_market.offer_count == 2
    assert iaa.higher_market.offer_count == 1


def test_iaa_event_trade_deletes_forwarded_offer_when_sold(iaa, called):
    iaa.lower_market.delete_offer = called
    iaa.event_trade(trade=Trade('trade_id',
                                datetime.now(),
                                iaa.higher_market.offers['id3'],
                                'owner',
                                'someone_else'),
                    market=iaa.higher_market)
    assert len(iaa.lower_market.delete_offer.calls) == 1


@pytest.fixture
def iaa2():
    lower_market = FakeMarket([Offer('id', 2, 2, 'other')])
    higher_market = FakeMarket([])
    owner = FakeArea('owner')
    iaa = InterAreaAgent(owner=owner, lower_market=lower_market, higher_market=higher_market)
    iaa.event_tick(area=iaa.owner)
    iaa.owner.current_tick += 2
    iaa.event_tick(area=iaa.owner)
    return iaa


def test_iaa_event_trade_buys_accepted_offer(iaa2, called):
    iaa2.lower_market.accept_offer = called
    iaa2.event_trade(trade=Trade('trade_id',
                                 datetime.now(),
                                 iaa2.higher_market.forwarded_offer,
                                 'owner',
                                 'someone_else'),
                     market=iaa2.higher_market)
    assert len(iaa2.lower_market.accept_offer.calls) == 1


@pytest.mark.skip('later')
def test_iaa_event_trade_buys_partial_accepted_offer(iaa2, called):
    iaa2.lower_market.accept_offer = called
    total_offer = iaa2.higher_market.forwarded_offer
    accepted_offer = Offer(total_offer.id, total_offer.price, 1, total_offer.seller)
    iaa2.event_trade(trade=Trade('trade_id',
                                 datetime.now(),
                                 accepted_offer,
                                 'owner',
                                 'someone_else'),
                     market=iaa2.higher_market)
    assert len(iaa2.lower_market.accept_offer.calls) == 1


def test_iaa_forwards_partial_offer(iaa2, called):
    full_offer = iaa2.lower_market.sorted_offers[0]
    residual_offer = Offer('residual', 2, 1.4, 'other')
    iaa2.event_offer_changed(market=iaa2.lower_market,
                             existing_offer=full_offer,
                             new_offer=residual_offer)
    assert iaa2.higher_market.forwarded_offer.energy == 1.4
