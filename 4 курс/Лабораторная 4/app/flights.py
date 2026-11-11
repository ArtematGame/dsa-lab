import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

AIRPORTS = 'OVB SVO DME VKO LED SVX KZN AER UFA KUF ROV KRR VOG CEK TJM OMS TOF KJA IKT UUD HTA YKS KHV VVO PKC UUS MMK ARH KGD MRV'.split()
START_DATE = date(2026, 10, 19)
DAYS = 120

# Один рейс 
# frozen=True объект нельзя изменить после создания
# slots=True объект занимает меньше памяти 
@dataclass(frozen=True, slots=True)
class Flight:
    carrier: str          # перевозчик
    number: str           # номер рейса
    origin: str           # аэропорт вылета
    destination: str      # аэропорт прилёта
    departure: datetime   # время вылета 
    arrival: datetime     # время прилёта 
    price: int            # цена 

    # словарь для ответа в формате JSON 
    def json(self):
        return {'carrier': self.carrier, 'number': self.number,
                'origin': self.origin, 'destination': self.destination,
                'departure': self.departure.isoformat(),
                'arrival': self.arrival.isoformat(), 'price': self.price}

    # Словарь из ответа поставщика в объект Flight 
    @classmethod
    def from_json(cls, row):
        return cls(**{**row, 'departure': datetime.fromisoformat(row['departure']),
                      'arrival': datetime.fromisoformat(row['arrival'])})

# Создать count рейсов источника source на дату day
def generate(day: date, source: str, count: int):
    rng = random.Random(f'42-{source}-{day.isoformat()}')
    midnight = datetime.combine(day, time(), timezone.utc)  
    flights = []
    for i in range(count):
        # Два разных случайных аэропорта откуда и куда
        origin, destination = rng.sample(AIRPORTS, 2)
        # Вылет в любую минуту суток (0-1439)
        departure = midnight + timedelta(minutes=rng.randrange(1440))
        flights.append(Flight(source, f'{source}{i+1:04d}', origin, destination,
                              # Полёт длится от 60 до 360 минут 
                              departure, departure + timedelta(minutes=rng.randint(60, 360)),
                              # Цена от 1500 до 20000 рублей
                              rng.randint(1500, 20000)))
    return flights
