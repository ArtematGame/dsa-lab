import unittest
from datetime import date

# импортируем классы из основного файла
from library_ddd import (
    BookCopy, BookCopyFactory, BookId, CopyId, DailyFineRate,
    DomainInvariantViolation, FineAmount, InMemoryCopyRepository,
    InMemoryLoanRepository, InvalidValueObject, LibraryService,
    LoanFactory, LoanId, LoanPeriod, ReaderId,
)


class LibraryDDDTests(unittest.TestCase):

    def setUp(self):
        # создаем пустые хранилища экземпляров и выдач
        self.copies = InMemoryCopyRepository()
        self.loans = InMemoryLoanRepository()

        # создаем сервис библиотеки и задаем штраф 10 рублей за день
        self.service = LibraryService(self.copies, self.loans, DailyFineRate(10))

        # добавляем один свободный экземпляр книги
        self.copies.save(BookCopy(CopyId(1), BookId(20)))

        # книга выдается с 1 по 10 сентября
        self.period = LoanPeriod(date(2026, 9, 1), date(2026, 9, 10))

    def issue(self, loan_id=1):
        # вспомогательный метод чтобы в каждом тесте заново не писать выдачу книги
        return self.service.issue_book(
            CopyId(1),
            LoanId(loan_id),
            ReaderId(1),
            self.period
        )

    def test_issue_and_return(self):
        # проверяем обычную выдачу и возврат книги без просрочки
        self.issue()

        # после выдачи экземпляр должен быть занят
        self.assertEqual("loaned", self.copies.get(CopyId(1)).status)

        # возвращаем книгу точно в срок
        loan = self.service.return_book(LoanId(1), date(2026, 9, 10))

        # выдача должна завершиться
        self.assertEqual("completed", loan.status)

        # просрочки нет поэтому штраф 0
        self.assertEqual(0, loan.fine.rubles)

        # после возврата экземпляр снова свободен
        self.assertEqual("available", self.copies.get(CopyId(1)).status)

    def test_prevents_double_issue(self):
        # проверяем что один экземпляр нельзя выдать двум читателям одновременно
        self.issue()

        # повторная выдача должна вызвать ошибку нарушения инварианта
        with self.assertRaises(DomainInvariantViolation):
            self.issue(2)

        # выдача с ID 2 не должна сохраниться
        self.assertNotIn(2, self.loans._data)

    def test_prevents_duplicate_loan_id(self):
        # создаем первую выдачу с ID 1
        self.issue()

        # добавляем второй свободный экземпляр книги
        self.copies.save(BookCopy(CopyId(2), BookId(20)))

        # пытаемся создать новую выдачу но снова с ID 1
        # одинаковые ID выдач использовать нельзя
        with self.assertRaises(DomainInvariantViolation):
            self.service.issue_book(
                CopyId(2),
                LoanId(1),
                ReaderId(2),
                self.period
            )

        # второй экземпляр после ошибки должен остаться свободным
        self.assertEqual("available", self.copies.get(CopyId(2)).status)

    def test_invalid_period(self):
        # проверяем что срок возврата не может быть раньше даты выдачи
        with self.assertRaises(InvalidValueObject):
            LoanPeriod(date(2026, 9, 10), date(2026, 9, 1))

    def test_invalid_values(self):
        # проверяем разные неправильные значения объектов-значений
        # ID не могут быть 0 отрицательными или True
        # штраф не может быть отрицательным или равным 0 для тарифа
        for construct in [
            lambda: BookId(0),
            lambda: ReaderId(-1),
            lambda: CopyId(True),
            lambda: FineAmount(-10),
            lambda: DailyFineRate(0)
        ]:
            # каждый неправильный объект должен вызвать ошибку
            with self.assertRaises(InvalidValueObject):
                construct()

    def test_overdue_fine(self):
        # проверяем расчет штрафа при просрочке
        self.issue()

        # возвращаем 13 сентября вместо 10
        loan = self.service.return_book(LoanId(1), date(2026, 9, 13))

        # просрочка должна быть 3 дня
        self.assertEqual(3, loan.days_overdue)

        # 3 дня * 10 рублей = 30 рублей
        self.assertEqual(30, loan.fine.rubles)

        # оплачиваем штраф
        self.service.pay_fine(LoanId(1))

        # проверяем что штраф отмечен как оплаченный
        self.assertTrue(
            self.loans.get(LoanId(1)).snapshot()["fine_paid"]
        )

    def test_wrong_return_date_does_not_change_state(self):
        # проверяем что нельзя вернуть книгу раньше даты ее выдачи
        self.issue()

        # книга выдана 1 сентября поэтому 31 августа вернуть ее нельзя
        with self.assertRaises(DomainInvariantViolation):
            self.service.return_book(LoanId(1), date(2026, 8, 31))

        # после ошибки выдача должна остаться активной
        self.assertEqual("active", self.loans.get(LoanId(1)).status)

        # экземпляр должен остаться выданным
        self.assertEqual("loaned", self.copies.get(CopyId(1)).status)

    def test_prevents_double_return(self):
        # проверяем что одну выдачу нельзя завершить два раза
        self.issue()

        # первый возврат проходит нормально
        self.service.return_book(LoanId(1), date(2026, 9, 10))

        # повторный возврат этой же выдачи должен вызвать ошибку
        with self.assertRaises(DomainInvariantViolation):
            self.service.return_book(LoanId(1), date(2026, 9, 11))

    def test_can_issue_again_after_return(self):
        # проверяем что после возврата экземпляр можно выдать снова
        self.issue()

        # возвращаем первую выдачу
        self.service.return_book(LoanId(1), date(2026, 9, 10))

        # создаем новую выдачу этого же экземпляра
        self.issue(2)

        # теперь активной должна быть выдача с ID 2
        self.assertEqual(
            LoanId(2),
            self.copies.get(CopyId(1)).active_loan_id
        )

    def test_copy_factory_rejects_corrupt_state(self):
        # проверяем фабрику восстановления экземпляра

        # неправильное состояние:
        # экземпляр указан как свободный но у него есть активная выдача
        invalid = {
            "copy_id": 1,
            "book_id": 20,
            "status": "available",
            "active_loan_id": 5
        }

        # фабрика должна заметить противоречие и вызвать ошибку
        with self.assertRaises(DomainInvariantViolation):
            BookCopyFactory.restore(invalid)

    def test_loan_factory_rejects_corrupt_fine(self):
        # проверяем фабрику восстановления выдачи
        self.issue()

        # возвращаем книгу с просрочкой 3 дня
        self.service.return_book(LoanId(1), date(2026, 9, 13))

        # получаем сохраненное состояние выдачи
        state = self.loans.get(LoanId(1)).snapshot()

        # специально подменяем правильный штраф 30 рублей на 1 рубль
        state["fine_rubles"] = 1

        # фабрика должна пересчитать штраф и заметить ошибку
        with self.assertRaises(DomainInvariantViolation):
            LoanFactory.restore(state)

    def test_loan_factory_rejects_paid_zero_fine(self):
        # проверяем что нельзя восстановить оплаченный штраф если штрафа вообще нет
        self.issue()

        # возвращаем книгу вовремя поэтому штраф равен 0
        self.service.return_book(LoanId(1), date(2026, 9, 10))

        # получаем сохраненное состояние
        state = self.loans.get(LoanId(1)).snapshot()

        # специально указываем что нулевой штраф якобы оплачен
        state["fine_paid"] = True

        # фабрика должна определить что такое состояние неправильное
        with self.assertRaises(DomainInvariantViolation):
            LoanFactory.restore(state)


if __name__ == "__main__":
    # запускаем все тесты
    unittest.main()
