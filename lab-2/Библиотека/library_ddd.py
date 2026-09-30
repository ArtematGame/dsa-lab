from dataclasses import dataclass  # Автоматически создаёт конструктор объектов-значений.
from datetime import date          # Тип для хранения и сравнения календарных дат.
from threading import RLock        # Защищает общую операцию от одновременного выполнения.
from typing import Protocol        # Описывает требования к репозиторию (его «интерфейс»).

# Доменные исключения

class DomainError(Exception):
    # Родитель всех доменных ошибок
    pass


class InvalidValueObject(DomainError):
    # Не удалось создать объект-значение:
    # ему передали неверные данные
    pass


class DomainInvariantViolation(DomainError):
    # Операция нарушает правило предметной области
    pass


class EntityNotFound(DomainError):
    # Нужный экземпляр книги или запись о выдаче не найдены
    pass


# объекты-значения
def _check_positive_id(value: int, label: str) -> None:
    # общая проверка для всех идентификаторов (целое число больше нуля)
    if type(value) is not int or value <= 0:
        raise InvalidValueObject(f"{label} должен быть положительным целым числом")


@dataclass(frozen=True)
class BookId:
    # идентификатор названия книги
    value: int

    def __post_init__(self) -> None:
        _check_positive_id(self.value, "ID книги")


@dataclass(frozen=True)
class CopyId:
    # иентификатор физического экземпляра
    value: int

    def __post_init__(self) -> None:
        _check_positive_id(self.value, "ID экземпляра")


@dataclass(frozen=True)
class ReaderId:
    # идентификатор читателя
    value: int

    def __post_init__(self) -> None:
        _check_positive_id(self.value, "ID читателя")


@dataclass(frozen=True)
class LoanId:
    # идентификатор выдачи книги
    value: int

    def __post_init__(self) -> None:
        _check_positive_id(self.value, "ID выдачи")


@dataclass(frozen=True)
class LoanPeriod:
    # Срок выдачи
    issue_date: date  # Дата выдачи
    due_date: date    # Плановая дата возврата

    def __post_init__(self) -> None:
        # нельзя передать строки или числа вместо объектов date
        if type(self.issue_date) is not date or type(self.due_date) is not date:
            raise InvalidValueObject("Даты выдачи и срока возврата должны иметь тип date")
        # Инвариант 3 плановый возврат должен быть позже выдачи.
        if self.due_date <= self.issue_date:
            raise InvalidValueObject("Плановая дата возврата должна быть позже даты выдачи")


@dataclass(frozen=True)
class DailyFineRate:
    # сколько рублей начисляем за день просрочки
    rubles: int

    def __post_init__(self) -> None:
        if type(self.rubles) is not int or self.rubles <= 0:
            raise InvalidValueObject("Штраф за день должен быть положительным числом рублей")


@dataclass(frozen=True)
class FineAmount:
    # Итоговая сумма штрафа может быть 0, но не меньше
    rubles: int

    def __post_init__(self) -> None:
        if type(self.rubles) is not int or self.rubles < 0:
            raise InvalidValueObject("Сумма штрафа не может быть отрицательной")

# 1 агрегат - экземпляр книги (BookCopy).
# он отвечает только за состояние физического экземпляра (свободен/выдан)
# изменяем состояние через методы issue() и return_copy()
class BookCopy:
    def __init__(self, copy_id: CopyId, book_id: BookId) -> None:
        # Проверяем, что переданы именно корректные типы идентификаторов
        if not isinstance(copy_id, CopyId) or not isinstance(book_id, BookId):
            raise InvalidValueObject("Нужны корректные CopyId и BookId")

        self._id = copy_id
        self._book_id = book_id
        self._status = "available"               # Новый экземпляр сначала свободен
        self._active_loan_id: LoanId | None = None  # Активной выдачи ещё нет

    # @property даёт читать поле через copy.id / copy.status, но не записывать copy.id
    @property
    def id(self) -> CopyId:
        return self._id

    @property
    def book_id(self) -> BookId:
        return self._book_id

    @property
    def status(self) -> str:
        return self._status

    @property
    def active_loan_id(self) -> LoanId | None:
        return self._active_loan_id

    def issue(self, loan_id: LoanId) -> None:
        #выдать экземпляр и проверить инварианты 1 и 2
        if not isinstance(loan_id, LoanId):
            raise InvalidValueObject("Нужен корректный LoanId")

        # если книга занята или уже указан ID активной выдачи, то выдача запрещена.
        if self._status != "available" or self._active_loan_id is not None:
            raise DomainInvariantViolation("Экземпляр уже выдан другому читателю")

        # после успешной проверки меняем состояние экземпляра.
        self._status = "loaned"          # экземпляр выдан
        self._active_loan_id = loan_id   # записываем в рамках какой выдачи

    def return_copy(self, loan_id: LoanId) -> None:
        # освободить экземпляр, проверка - возврат относится к текущей выдаче
        # нельзя вернуть свободную книгу или указать ID другой выдачи
        if self._status != "loaned" or self._active_loan_id != loan_id:
            raise DomainInvariantViolation("У экземпляра нет такой активной выдачи")

        self._status = "available"  # После возврата книгу снова можно выдавать
        self._active_loan_id = None  # У экземпляра больше нет активной выдачи

    def snapshot(self) -> dict:
        # словарь для сохранения состояния экземпляра в памяти
        return {
            "copy_id": self._id.value,
            "book_id": self._book_id.value,
            "status": self._status,
            # Если активной выдачи нет, сохраняем None, иначе сохраняем её числовой ID.
            "active_loan_id": (
                self._active_loan_id.value if self._active_loan_id is not None else None
            ),
        }


# агрегат 2 - выдача (Loan)
# отвечает за читателя, сроки, фактический возврат и штраф
# принцип DDD: Loan хранит только copy_id, а не объект BookCopy целиком.
class Loan:
    def __init__(
        self,
        loan_id: LoanId,
        copy_id: CopyId,
        reader_id: ReaderId,
        period: LoanPeriod,
        daily_rate: DailyFineRate,
    ) -> None:
        # проверяем все значения, необходимые для создания выдачи
        if not (
            isinstance(loan_id, LoanId)
            and isinstance(copy_id, CopyId)
            and isinstance(reader_id, ReaderId)
            and isinstance(period, LoanPeriod)
            and isinstance(daily_rate, DailyFineRate)
        ):
            raise InvalidValueObject("Некорректные данные при создании выдачи")

        self._id = loan_id
        self._copy_id = copy_id         
        self._reader_id = reader_id
        self._period = period
        self._daily_rate = daily_rate
        self._status = "active"        # при создании выдача активна
        self._return_date: date | None = None  # книгу ещё не вернули
        self._days_overdue = 0         # пока нет просрочки
        self._fine = FineAmount(0)     # пока нет штрафа
        self._fine_paid = False        # признак оплаты штрафа

    # доступ к данным для чтения, но не менять их напрямую
    @property
    def id(self) -> LoanId:
        return self._id

    @property
    def copy_id(self) -> CopyId:
        return self._copy_id

    @property
    def status(self) -> str:
        return self._status

    @property
    def fine(self) -> FineAmount:
        return self._fine

    @property
    def days_overdue(self) -> int:
        return self._days_overdue

    def finish(self, return_date: date) -> None:
        # завершить выдачу и рассчитать штраф, проверка инвариантов 5-7
        # 5 - уже завершённую выдачу нельзя завершить повторно.
        if self._status != "active":
            raise DomainInvariantViolation("Эта выдача уже завершена")

        # проверяем, что нам передали настоящую календарную дату
        if type(return_date) is not date:
            raise InvalidValueObject("Нужна фактическая дата возврата типа date")

        # 6 - фактическая дата возврата не может быть раньше выдачи книги
        if return_date < self._period.issue_date:
            raise DomainInvariantViolation("Дата возврата не может быть раньше даты выдачи")

        # 7 - считаем просрочку (фактический возврат минус плановый срок)
        # .days — разница между датами в днях.
        # max(0, ...) не допускает отрицательную просрочку при раннем возврате
        days = max(0, (return_date - self._period.due_date).days)

        # записываем окончательные данные о возврате
        self._return_date = return_date
        self._days_overdue = days
        self._fine = FineAmount(days * self._daily_rate.rubles)  # Дни * руб./день.
        self._status = "completed"  # Выдача закрыта

    def pay_fine(self) -> None:
        # пометить штраф как оплаченный, если он существует и ещё не был оплачен
        if self._status != "completed" or self._fine.rubles == 0:
            raise DomainInvariantViolation("По данной выдаче нет штрафа для оплаты")
        if self._fine_paid:
            raise DomainInvariantViolation("Штраф уже оплачен")
        self._fine_paid = True

    def snapshot(self) -> dict:
        # все данные выдачи в словарь
        return {
            "loan_id": self._id.value,
            "copy_id": self._copy_id.value,
            "reader_id": self._reader_id.value,
            "issue_date": self._period.issue_date.isoformat(),
            "due_date": self._period.due_date.isoformat(),
            "daily_rate": self._daily_rate.rubles,
            # если книгу ещё не вернули, вместо даты сохраняется None.
            "return_date": self._return_date.isoformat() if self._return_date else None,
            "status": self._status,
            "days_overdue": self._days_overdue,
            "fine_rubles": self._fine.rubles,
            "fine_paid": self._fine_paid,
        }


# фабрики восстановления
# snapshot() превращает объект в словарь; restore() выполняет обратную операцию.
# повторим проверки
def _saved_date(raw: str) -> date:
    """Превратить строку из словаря («2026-09-01») обратно в объект date."""
    if not isinstance(raw, str):
        raise InvalidValueObject("Сохранённая дата должна быть строкой ISO")
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        # Переводим техническую ошибку разбора даты в доменную ошибку
        raise InvalidValueObject("Некорректная дата в сохранённых данных") from exc


class BookCopyFactory:
    #Создаёт экземпляр книги из ранее сохранённого словаря

    @staticmethod  # Можно вызвать BookCopyFactory.restore(data), не создавая объект фабрики.
    def restore(data: dict) -> BookCopy:
        # Сначала создаём свободный экземпляр и ID заново валидируются.
        copy = BookCopy(CopyId(data["copy_id"]), BookId(data["book_id"]))
        status, active_id = data["status"], data["active_loan_id"]

        # свободен, активной выдачи нет.
        if status == "available" and active_id is None:
            return copy

        # выдан и есть ID выдачи
        if status == "loaned" and active_id is not None:
            # вместо присваивания copy._status повторно вызываем метод агрегата
            copy.issue(LoanId(active_id))
            return copy

        raise DomainInvariantViolation("Несогласованное сохранённое состояние экземпляра")


class LoanFactory:
    # восстанавливает выдачу, проверяя сроки, состояние и сумму штрафа

    @staticmethod
    def restore(data: dict) -> Loan:
        # Создаём новую активную выдачу (снова валидация)
        loan = Loan(
            LoanId(data["loan_id"]),
            CopyId(data["copy_id"]),
            ReaderId(data["reader_id"]),
            LoanPeriod(_saved_date(data["issue_date"]), _saved_date(data["due_date"])),
            DailyFineRate(data["daily_rate"]),
        )
        status = data["status"]

        # Признак оплаты обязан быть True или False.
        if type(data["fine_paid"]) is not bool:
            raise DomainInvariantViolation("Некорректный признак оплаты штрафа")

        if status == "active":
            # У активной выдачи ещё не может быть фактического возврата и штрафа.
            if (
                data["return_date"] is not None
                or data["days_overdue"] != 0
                or data["fine_rubles"] != 0
                or data["fine_paid"]
            ):
                raise DomainInvariantViolation("У активной выдачи не может быть возврата или штрафа")
            return loan

        if status == "completed":
            # Заново выполняем finish()
            loan.finish(_saved_date(data["return_date"]))

            # Сверяем расчёт с сохранёнными числами
            if (
                loan.days_overdue != data["days_overdue"]
                or loan.fine.rubles != data["fine_rubles"]
            ):
                raise DomainInvariantViolation("Сохранённый штраф не соответствует датам")

            # Если в сохранённом состоянии штраф был оплачен, применяем метод агрегата.
            if data["fine_paid"]:
                loan.pay_fine()
            return loan

        # Допустимые статусы (active и completed)
        raise DomainInvariantViolation("Неизвестный статус выдачи")


# порты
# описываем нужные методы
# ... означают, что конкретная реализация будет написана ниже
# доменная логика не знает, словарь это, файл или реальная база данных
class CopyRepository(Protocol):
    def get(self, copy_id: CopyId) -> BookCopy: ...
    def save(self, copy: BookCopy) -> None: ...


class LoanRepository(Protocol):
    def get(self, loan_id: LoanId) -> Loan: ...
    def add(self, loan: Loan) -> None: ...   # Создать новую выдачу
    def save(self, loan: Loan) -> None: ...  # Обновить существ выдачу


# доменный сервис
# Выдача книги меняет BookCopy и Loan
# координация этих действий вынесена в LibraryService
class LibraryService:
    def __init__(
        self, copies: CopyRepository, loans: LoanRepository, daily_rate: DailyFineRate
    ) -> None:
        self._copies = copies        # порт читаем/сохраняем экземпляры
        self._loans = loans          # порт читаем/сохраняем выдачи
        self._daily_rate = daily_rate
        # RLock защищает операции, выполняемые одним экземпляром сервиса
        self._lock = RLock()

    def issue_book(
        self, copy_id: CopyId, loan_id: LoanId, reader_id: ReaderId, period: LoanPeriod
    ) -> Loan:
        # выдать книгу создать выдачу и пометить экземпляр занятым
        with self._lock:
            copy = self._copies.get(copy_id)  # Найти нужный физический экземпляр
            loan = Loan(loan_id, copy_id, reader_id, period, self._daily_rate)
            copy.issue(loan_id)               # Проверить доступность экземпляра
            self._loans.add(loan)             # Добавить новую выдачу (ID не должен повторяться)
            self._copies.save(copy)          # Сохранить статус "выдан" у экземпляра
            return loan                      # Вернуть созданную выдачу вызывающему коду

    def return_book(self, loan_id: LoanId, return_date: date) -> Loan:
        # принять возврат (завершить выдачу, рассчитать штраф и освободить экземпляр)
        with self._lock:
            loan = self._loans.get(loan_id)         # Найти запись о выдаче
            copy = self._copies.get(loan.copy_id)  # По ID из выдачи найти экземпляр
            loan.finish(return_date)              # Проверить дату и рассчитать штраф
            copy.return_copy(loan_id)             # Освободить именно этот экземпляр
            self._loans.save(loan)                 # Сохранить завершённую выдачу
            self._copies.save(copy)                # Сохранить статус "свободен"
            return loan

    def pay_fine(self, loan_id: LoanId) -> Loan:
        # провести оплату штрафа
        with self._lock:
            loan = self._loans.get(loan_id)
            loan.pay_fine()          # Агрегат сам проверяет можно ли оплатить штраф
            self._loans.save(loan)   # Сохранить признак оплаты
            return loan


# Хранилища в памяти - словари питона
# Ключ — числовой ID, значение — словарь с сохранёнными полями объекта
# При чтении вызываем фабрику она восстанавливает объект и проверяет правила.
class InMemoryCopyRepository:
    def __init__(self) -> None:
        self._data: dict[int, dict] = {} 

    def get(self, copy_id: CopyId) -> BookCopy:
        if copy_id.value not in self._data:
            raise EntityNotFound("Экземпляр не найден")
        # .copy() создаёт отдельный словарь и фабрика проверяет сохранённые данные
        return BookCopyFactory.restore(self._data[copy_id.value].copy())

    def save(self, copy: BookCopy) -> None:
        # Получаем snapshot экземпляра и сохраняем его по числовому ID
        self._data[copy.id.value] = copy.snapshot()


class InMemoryLoanRepository:
    def __init__(self) -> None:
        self._data: dict[int, dict] = {}

    def get(self, loan_id: LoanId) -> Loan:
        if loan_id.value not in self._data:
            raise EntityNotFound("Выдача не найдена")
        return LoanFactory.restore(self._data[loan_id.value].copy())

    def add(self, loan: Loan) -> None:
        # При создании записи нельзя использовать уже занятый ID выдачи
        if loan.id.value in self._data:
            raise DomainInvariantViolation("ID выдачи уже используется")
        self._data[loan.id.value] = loan.snapshot()

    def save(self, loan: Loan) -> None:
        if loan.id.value not in self._data:
            raise EntityNotFound("Нельзя обновить несуществующую выдачу")
        self._data[loan.id.value] = loan.snapshot()
