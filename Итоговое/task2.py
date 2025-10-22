def roman_to_int(s: str) -> int:
    """
    Преобразует римское число (например, 'MCMXCIV') в целое десятичное.
    
    Поддерживает разрешённые вычитательные пары:
      IV (4), IX (9), XL (40), XC (90), CD (400), CM (900)
    Иначе — использует стандартное сложение слева направо.

    Параметры:
        s (str): римское число (регистр неважен), напр. 'III', 'LVIII', 'MCMXCIV'.

    Возвращает:
        int: десятичное значение.

    Исключения:
        ValueError — при пустой строке или недопустимых символах/парах.
    """
    if not isinstance(s, str) or not s.strip():
        raise ValueError("Ожидается непустая строка с римским числом")

    s = s.upper().strip()
    vals = {
        'I': 1, 'V': 5, 'X': 10,
        'L': 50, 'C': 100, 'D': 500, 'M': 1000
    }
    allowed_sub = {'IV', 'IX', 'XL', 'XC', 'CD', 'CM'}

    total = 0
    i = 0
    n = len(s)

    while i < n:
        c = s[i]
        if c not in vals:
            raise ValueError(f"Недопустимый символ: {c!r}")

        # Смотрим на следующую букву для возможной вычитательной пары
        if i + 1 < n:
            c2 = s[i + 1]
            if c2 not in vals:
                raise ValueError(f"Недопустимый символ: {c2!r}")

            v1, v2 = vals[c], vals[c2]
            if v1 < v2:
                pair = c + c2
                if pair not in allowed_sub:
                    raise ValueError(f"Недопустимая вычитательная пара: {pair!r}")
                total += v2 - v1
                i += 2
                continue

        # Обычное сложение
        total += vals[c]
        i += 1

    return total

print(roman_to_int("III"))      # 3
print(roman_to_int("LVIII"))    # 58   (L=50, V=5, III=3)
print(roman_to_int("MCMXCIV"))  # 1994 (M=1000, CM=900, XC=90, IV=4)

# Обработка ошибок
# roman_to_int("")         -> ValueError
# roman_to_int("IC")       -> ValueError (недопустимая пара; должно быть XCIX)
# roman_to_int("XM")       -> ValueError (недопустимая пара; должно быть CMXC...)
