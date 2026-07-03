# Node 3

# -*- coding: utf-8 -*-
import clr

# Импорт необходимых библиотек Revit API
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *

# Импорт сервисов документа и транзакций
clr.AddReference('RevitServices')
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

uidoc = DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument

if IN is None:
    raise Exception("Ошибка: На вход IN не передан целевой вид.")

# --- СТРОГОЕ ВЫПОЛНЕНИЕ ПУНКТА 5 ТЗ (Распаковка списков Dynamo) ---
raw_input = IN
while isinstance(raw_input, list):
    if len(raw_input) == 0:
        raise Exception("Ошибка: Поданный список на входе IN пуст.")
    raw_input = raw_input[0]

# Принудительно достаем чистый низкоуровневый объект Autodesk.Revit.DB.View
if hasattr(raw_input, 'InternalElement'):
    target_view = raw_input.InternalElement
else:
    target_view = raw_input

# Проверка, что мы получили именно валидный объект вида Revit API
if not target_view or not isinstance(target_view, View):
    raise Exception("Ошибка: Объект на входе не является валидным видом Revit API.")

# Принудительно закрываем транзакцию Dynamo, освобождая поток Revit
TransactionManager.Instance.ForceCloseTransaction()

# Отправляем асинхронный запрос на смену вида (теперь типы совпадают на 100%)
uidoc.RequestViewChange(target_view)

# Мгновенно выходим и передаем чистый вид дальше в Ноду 4
OUT = target_view

