from d3a.exceptions import MarketException
from d3a.models.appliance.mixins import SwitchableMixin
from d3a.models.appliance.simple import SimpleAppliance
from d3a.models.events import Trigger
from d3a.models.strategy.base import BaseStrategy
from d3a.models.strategy.const import DEFAULT_RISK, FRIDGE_TEMPERATURE, MAX_FRIDGE_TEMP, \
    MIN_FRIDGE_TEMP, FRIDGE_MIN_NEEDED_ENERGY, MAX_RISK


# TODO Find realistic values for consumption as well as temperature changes
# TODO Fridge needs to buy 10% of total bought energy as option

class FridgeStrategy_Balancing(BaseStrategy):
    def __init__(self, risk=DEFAULT_RISK):
        super().__init__()
        self.risk = risk
        self.fridge_temp = FRIDGE_TEMPERATURE
        self.open_spot_markets = []
        self.max_fridge_temp = 0
        self.min_fridge_temp = 0

    def event_activate(self):
        self.open_spot_markets = list(self.area.markets.values())
        tem_increase_per_tick = self.area.config.tick_length.in_seconds() * round((0.02 / 60), 6)
        tps = self.area.config.ticks_per_slot
        self.max_fridge_temp = MAX_FRIDGE_TEMP
        # Makes sure that the fridge stays above MIN_FRIDGE TEMP
        # even if he buys energy in the latest opened spot market
        self.min_fridge_temp = MIN_FRIDGE_TEMP - (len(self.open_spot_markets) *
                                                  tem_increase_per_tick * tps)

    def event_tick(self, *, area):
        # The not cooled fridge warms up (0.02 / 60)C up every second
        self.fridge_temp += self.area.config.tick_length.in_seconds() * round((0.02 / 60), 6)

        # Only trade after the 4th tick
        tick_in_slot = area.current_tick % area.config.ticks_per_slot
        if tick_in_slot < 5:
            return

        # Assuming a linear correlation between accepted price and risk
        median_risk = MAX_RISK / 2
        # The threshold buying price depends on historical market data
        min_historical_price, max_historical_price = self.area.historical_min_max_price
        average_market_price = self.area.historical_avg_price
        fridge_temp_domain = MAX_FRIDGE_TEMP - MIN_FRIDGE_TEMP

        # normalized _fridge_temp has a value between 1 and -1
        # E.g.: If self.fridge_temp = 8 the normalized_fridge_temp is 1
        self.fridge_temp = (
            (self.fridge_temp - (0.5 * (MAX_FRIDGE_TEMP + MIN_FRIDGE_TEMP))
             ) / (0.5 * fridge_temp_domain)
        )

        # normalized _fridge_temp has a value between 1 and -1
        # If self.fridge_temp = 8 the normalized_fridge_temp is 1
        normalized_fridge_temp = (
            (self.fridge_temp - (0.5 * (MAX_FRIDGE_TEMP + MIN_FRIDGE_TEMP))
             ) / (0.5 * fridge_temp_domain)
        )

        # deviation_from_average is the value that determines the deviation (in percentage of
        # the average market price)
        max_deviation_from_average = 0.1 * average_market_price

        # accepted_price_at_highest_risk is the threshold price while going with the most risky
        # strategy This depends on the max and min historical price! (through the variable
        # deviation_from_average)
        accepted_price_at_highest_risk = (average_market_price - max_deviation_from_average)

        # This slope is used to calculate threshold prices for
        # risks other than the maximum risk strategy
        risk_price_slope = (
            (
                average_market_price - accepted_price_at_highest_risk
            ) / (MAX_RISK - median_risk)
        )

        # risk_dependency_of_threshold_price calculates a threshold price
        # with respect to the risk variable. Therefore, we use
        # the point in the risk-price domain with the lowest possible price.
        # This is of course the point of highest possible risk.
        # Then we add the slope times the risk (lower risk needs to result in a higher price)
        risk_dependency_of_threshold_price = (accepted_price_at_highest_risk +
                                              ((MAX_RISK - self.risk) / 100) * risk_price_slope
                                              )

        # temperature_dependency_of_threshold_price calculates the Y intercept that results
        # out of a different temperature of the fridge
        # If the fridge_temp is 8 degrees the fridge needs to cool no matter how high the price is
        # If the fridge_temp is 4 degrees the fridge can't cool no matter how low the price is
        # If the normalized fridge temp is above the average value we are tempted to cool more
        # If the normalized fridge temp is below the average value we are tempted to cool less
        if normalized_fridge_temp >= 0:
            temperature_dependency_of_threshold_price = normalized_fridge_temp * (
                max_historical_price - risk_dependency_of_threshold_price
            )
        else:
            temperature_dependency_of_threshold_price = normalized_fridge_temp * (
                risk_dependency_of_threshold_price - min_historical_price
            )
        threshold_price = (risk_dependency_of_threshold_price +
                           temperature_dependency_of_threshold_price
                           )

        # Here starts the logic if energy should be bought
        for market in self.open_spot_markets:
            for offer in market.sorted_offers:
                # offer.energy * 1000 is needed to get the energy in Wh
                # 0.05 is the temperature decrease per cooling period and minimal needed energy
                # *2 is needed because we need to cool and equalize the increase
                #  of the temperature (see event_market_cycle) as well
                cooling_temperature = (((offer.energy * 1000) / FRIDGE_MIN_NEEDED_ENERGY)
                                       * 0.05 * 2)
                if (
                            (((offer.price / offer.energy) <= threshold_price
                              and self.fridge_temp - cooling_temperature > self.min_fridge_temp
                              )
                             or self.fridge_temp >= self.max_fridge_temp
                             )
                        and (offer.energy * 1000) >= FRIDGE_MIN_NEEDED_ENERGY
                ):
                    try:
                        self.accept_offer(market, offer)
                        self.log.debug("Buying %s", offer)
                        self.fridge_temp -= cooling_temperature
                        break
                    except MarketException:
                        # Offer already gone etc., try next one.
                        self.log.exception("Couldn't buy")
                        continue
        else:
            if self.fridge_temp >= MAX_FRIDGE_TEMP:
                self.log.critical("Need energy (temp: %.2f) but can't buy", self.fridge_temp)
                try:
                    self.log.info("cheapest price is is %s",
                                  list(self.open_spot_markets[0].sorted_offers)[-1].price)

                except IndexError:
                    self.log.critical("Crap no offers available")

    def event_market_cycle(self):
        self.log.info("Temperature: %.2f", self.fridge_temp)
        self.open_spot_markets = list(self.area.markets.values())


class FridgeAppliance_Balancing(SwitchableMixin, SimpleAppliance, FridgeStrategy_Balancing):
    available_triggers = [
        Trigger('open', state_getter=lambda s: s.is_door_open,
                help="Open fridge door for 'duration' ticks."),
        Trigger('close', state_getter=lambda s: not s.is_door_open,
                help="Close fridge door immediately if open.")
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.force_cool_energy = -0.05
        self.loss = 0
        self.cooling_gain = 0
        self.door_open_loss = 0
        self.is_door_open = False

    def event_activate(self):
        FridgeStrategy_Balancing.event_activate(self)

        tick_length = self.area.config.tick_length.in_seconds()
        # If running cool 0.01C per second
        self.cooling_gain = tick_length * -0.01
        # Fridge with door open heats up 0.9C per minute
        self.door_open_loss = tick_length * (0.9 / 60)

    def event_tick(self, *, area):
        SimpleAppliance.event_tick(self, area=area)

    def report_energy(self, energy):
        if self.is_door_open:
            self.owner.strategy.fridge_temp += self.door_open_loss

        if energy:
            self.owner.strategy.fridge_temp += self.cooling_gain
        else:
            return

        if self.owner.strategy.fridge_temp > self.max_fridge_temp and not energy:
            energy = self.force_cool_energy
            self.owner.strategy.fridge_temp += self.cooling_gain

        super().report_energy(energy)
