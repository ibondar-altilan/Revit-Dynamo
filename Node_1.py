# Node 1

# -*- coding: utf-8 -*-
import clr

# Импорт необходимых библиотек Revit API
clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import TaskDialog, TaskDialogCommonButtons

# Импорт сервисов документа
clr.AddReference('RevitServices')
from RevitServices.Persistence import DocumentManager

doc = DocumentManager.Instance.CurrentDBDocument

def get_revit_element(dynamo_element):
    if not dynamo_element: return None
    if hasattr(dynamo_element, 'InternalElement'): return dynamo_element.InternalElement
    return dynamo_element

def get_parameter_value_string(element, param_name):
    param = element.LookupParameter(param_name)
    if not param or not param.HasValue: return ""
    if param.StorageType == StorageType.String: return param.AsString() or ""
    return param.AsValueString() or ""

# --- ШАГ 1: ВАЛИДАЦИЯ И ЖЕЛЕЗНАЯ РАСПАКОВКА ВХОДА СТРОГО ПО ПУНКТУ 5 ---
if IN is None: 
    raise Exception("Ошибка: На вход IN не подан выключатель.")

# Рекурсивная распаковка ЛЮБЫХ списков и подсписков Dynamo
raw_input = IN
while isinstance(raw_input, list):
    if len(raw_input) == 0:
        raise Exception("Ошибка: Поданный список на входе IN пуст.")
    raw_input = raw_input[0] # Извлекаем первый элемент, пока не дойдем до объекта

revit_switch = get_revit_element(raw_input)

if not revit_switch:
    raise Exception("Ошибка: Не удалось получить внутренний элемент Revit.")

# Чтение номера цепи выключателя
circuit_number = get_parameter_value_string(revit_switch, "Номер цепи")
if not circuit_number:
    raise Exception("Ошибка: Параметр 'Номер цепи' пуст.")
circuit_display_name = circuit_number.strip()
circuit_number_clean = circuit_display_name.lower()

# --- ШАГ 2: СБОР ТРАСС ПО ВСЕЙ МОДЕЛИ ---
target_family_keyword = "TSL_GM_в_Участок трассы_Горизонтальный"
collector = FilteredElementCollector(doc).OfClass(FamilyInstance).WhereElementIsNotElementType()

counted_elements = []

for item in collector:
    if not item.Symbol or not item.Symbol.Family: continue
    if target_family_keyword not in item.Symbol.Family.Name: continue
    
    tsl_circuit = get_parameter_value_string(item, "TSL_Номер питающей цепи")
    if circuit_number_clean in tsl_circuit.strip().lower():
        counted_elements.append(item)

# --- ШАГ 3: ПРОВЕРКА НАЛИЧИЯ И ВЫВОД ОКНА ПРЕДУПРЕЖДЕНИЯ ---
if not counted_elements: 
    dialog_title = "Предупреждение"
    dialog_message = f"Для цепи {circuit_display_name} участков трассы не найдено."
    
    # Статический метод гарантирует работу в CPython 3
    TaskDialog.Show(dialog_title, dialog_message, TaskDialogCommonButtons.Close)
    
    raise Exception(f"Выполнение остановлено: не найдена трасса для цепи {circuit_display_name}.")

# Если элементы найдены — передаем список 3D элементов дальше во вторую ноду
OUT = counted_elements
