from __future__ import annotations

from datetime import datetime, timedelta


class ClockMovedBack(Exception):
    pass


class SystemClock:
    # Часы показывают «системное время + сдвиг» Сдвиг можно двигать только вперёд 
    def __init__(self) -> None:
        self._offset = timedelta(0)

    def now(self) -> datetime:
        return datetime.now() + self._offset

    def move_to(self, moment: datetime) -> None:
        if not isinstance(moment, datetime):
            raise TypeError("moment должен быть datetime")
        current = self.now()
        # Назад нельзя иначе можно «переиграть» уже случившиеся события
        if moment < current:
            raise ClockMovedBack("Перевод часов назад запрещён")
        # Считаем новый сдвиг относительно реального системного времени
        self._offset = moment - datetime.now()