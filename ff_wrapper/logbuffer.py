from typing import List


def progress_str_to_dict(progress_log: str) -> dict:
    progress_log = progress_log.strip().split(' ')
    result = {}
    for line in progress_log:
        k, v = line.split('=')
        result[k] = v
    return result


class LogBuffer:

    def __init__(self, size_max):
        self._next = 0
        self.max = size_max
        self._data = [None] * size_max

    def append(self, item):
        self._data[self._next % self.max] = item
        self._next += 1

    def get_last_items(self, n) -> (List[str], int):
        # Получить n количество последних строк
        # Возвращает список строк и текущую позицию лога

        # Если количество запрашиваемых элементов больше, чем максимальное количество строк
        if n > self.max:
            return self.get_all()
        # Если нет переполнения или это последний элемент перед ним
        if self._next <= self.max:
            if self._next <= n:
                return self._data[:self._next], self._next
            return self._data[self._next-n:self._next], self._next
        # Переполнение
        else:
            split = self._next % self.max
            if split == 0:
                return self._data[-n:], self._next
            elif n > split:
                return self._data[self.max - (n - split):] + self._data[:split], self._next
            else:
                return self._data[split-n:split], self._next

    def get_all(self) -> (List[str], int):
        # Возвращает список строк и текущую позицию лога
        if self._next < self.max:
            return self._data[:self._next], self._next
        split = self._next % self.max
        return self._data[split:] + self._data[:split], self._next

    def get_current_position(self) -> int:
        return self._next
