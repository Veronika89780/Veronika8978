from typing import Iterable

def is_monotonic(nums: Iterable[int]) -> bool:
    """
    Возвращает True, если последовательность nums монотонна
    (неубывающая или невозрастающая), иначе False.

    Определение:
      - неубывающая: nums[i] <= nums[i+1] для всех i
      - невозрастающая: nums[i] >= nums[i+1] для всех i

    Пограничные случаи:
      - Пустой список и список из одного элемента считаются монотонными.

    Примеры:
      is_monotonic([1,2,2,3])  -> True
      is_monotonic([6,5,4,4])  -> True
      is_monotonic([1,3,2])    -> False
    """
    nums = list(nums)
    if len(nums) < 2:
        return True

    nondecreasing = True
    nonincreasing = True

    for i in range(1, len(nums)):
        if nums[i] > nums[i - 1]:
            nonincreasing = False
        elif nums[i] < nums[i - 1]:
            nondecreasing = False

        # Ранняя остановка
        if not (nondecreasing or nonincreasing):
            return False

    return True

print(is_monotonic([1,2,2,3]))  # True
print(is_monotonic([6,5,4,4]))  # True
print(is_monotonic([1,3,2]))    # False
