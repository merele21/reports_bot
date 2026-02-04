"""
Утилиты для работы с группировкой пользователей по display_name
"""
from typing import List, Dict, Set
from bot.database.models import User


def group_users_by_display_name(users: List[User]) -> Dict[str, List[User]]:
    """
    Группирует пользователей по display_name.
    Пользователи без display_name группируются индивидуально по telegram_id.
    
    Args:
        users: Список пользователей
        
    Returns:
        Словарь {ключ_группировки: [список_пользователей]}
    """
    groups = {}
    
    for user in users:
        # Если есть display_name, группируем по нему
        if user.display_name:
            key = f"display:{user.display_name}"
        else:
            # Если нет display_name, каждый пользователь в своей группе
            key = f"user:{user.telegram_id}"
        
        if key not in groups:
            groups[key] = []
        groups[key].append(user)
    
    return groups


def get_display_name_for_user(user: User) -> str:
    """
    Возвращает отображаемое имя пользователя для отчетов.
    
    Args:
        user: Объект пользователя
        
    Returns:
        Строка для отображения (display_name или full_name)
    """
    if user.display_name:
        return user.display_name
    return user.full_name


def format_user_mention(user: User) -> str:
    """
    Форматирует упоминание пользователя для сообщений.
    
    Args:
        user: Объект пользователя
        
    Returns:
        Строка с упоминанием (@username или имя)
    """
    if user.username:
        return f"@{user.username}"
    
    if user.display_name:
        return user.display_name
    
    return user.full_name


def get_unique_display_names(users: List[User]) -> Set[str]:
    """
    Возвращает уникальные display_name из списка пользователей.
    
    Args:
        users: Список пользователей
        
    Returns:
        Множество уникальных display_name
    """
    return {user.display_name for user in users if user.display_name}


def filter_one_user_per_display_name(users: List[User]) -> List[User]:
    """
    Фильтрует список пользователей, оставляя только по одному представителю
    для каждого display_name. Пользователи без display_name остаются все.
    
    Args:
        users: Список пользователей
        
    Returns:
        Отфильтрованный список пользователей
    """
    seen_display_names = set()
    result = []
    
    for user in users:
        if user.display_name:
            if user.display_name not in seen_display_names:
                seen_display_names.add(user.display_name)
                result.append(user)
        else:
            # Пользователей без display_name добавляем всех
            result.append(user)
    
    return result


def has_any_account_submitted(users_in_group: List[User], check_func) -> bool:
    """
    Проверяет, сдал ли хотя бы один аккаунт из группы отчет.
    
    Args:
        users_in_group: Список пользователей в группе (с одинаковым display_name)
        check_func: Async функция проверки (принимает user.id, возвращает bool/object)
        
    Returns:
        True если хотя бы один аккаунт сдал отчет
        
    Note:
        Это синхронная обертка, реальная проверка должна быть в async коде
    """
    # Эта функция будет использоваться как концепция в async коде
    pass
