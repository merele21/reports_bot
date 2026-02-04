"""
Утилиты для группировки пользователей по store_id
"""
from typing import List, Dict, Tuple
from bot.database.models import User


def group_users_by_store(users: List[User]) -> Dict[str, List[User]]:
    """
    Группирует пользователей по store_id.
    Пользователи без store_id группируются индивидуально.

    Args:
        users: Список пользователей

    Returns:
        Словарь {store_id: [список_пользователей]}
        Для пользователей без store_id: {f"no_store_{telegram_id}": [user]}

    Примеры:
        {"MSK-001": [user1, user2], "SPB-042": [user3]}
    """

    groups = {}

    for user in users:
        if user.store_id:
            key = user.store_id
        else:
            # Пользователи без магазина - каждый сам по себе
            key = f"no_store_{user.telegram_id}"

        if key not in groups:
            groups[key] = []
        groups[key].append(user)

    return groups


def format_store_mention(store_id: str, users: List[User]) -> str:
    """
    Форматирует упоминание магазина для отчетов.

    Args:
        store_id: ID магазина или "no_store_XXX"
        users: Список пользователей этого магазина

    Returns:
        "MSK-001" - для магазинов
        "@username" или "Иван Иванов" - для пользователей без магазина

    Примеры:
        format_store_mention("MSK-001", [user1, user2]) → "MSK-001"
        format_store_mention("no_store_123", [user]) → "@ivan" или "Иван"
    """

    if store_id.startswith("no_store_"):
        # Это пользователь без магазина
        user = users[0]
        if user.username:
            return f"@{user.username}"
        return user.full_name or f"ID:{user.telegram_id}"

    # Это магазин
    return store_id


def get_store_users_list(users: List[User]) -> str:
    """
    Возвращает список пользователей магазина через запятую.

    Args:
        users: Список пользователей

    Returns:
        Строка вида "@user1, @user2, Иван Иванов"

    Примеры:
        get_store_users_list([user1, user2]) → "@ivan, @petr"
    """

    mentions = []
    for user in users:
        if user.username:
            mentions.append(f"@{user.username}")
        else:
            mentions.append(user.full_name or f"ID:{user.telegram_id}")

    return ", ".join(mentions)


def has_store_submitted_report(
    store_users: List[User],
    reports_dict: Dict[int, bool]
) -> bool:
    """
    Проверяет, сдал ли хотя бы один пользователь магазина отчет.

    Args:
        store_users: Список пользователей магазина
        reports_dict: Словарь {user_id: has_report}

    Returns:
        True если хотя бы один пользователь магазина сдал отчет

    Примеры:
        has_store_submitted_report([user1, user2], {1: True, 2: False}) → True
        has_store_submitted_report([user1, user2], {1: False, 2: False}) → False
    """

    for user in store_users:
        if reports_dict.get(user.id, False):
            return True
    return False