# Node 4
# Назначение:
# 1) Ждет фактического переключения Revit на целевой план.
# 2) Контролирует таймаут ожидания смены активного вида.
# 3) Возвращает активный целевой вид или None при неудаче.

# -*- coding: utf-8 -*-
import clr
import time

clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *

clr.AddReference('RevitServices')
from RevitServices.Persistence import DocumentManager

clr.AddReference('System.Windows.Forms')
import System.Windows.Forms

doc = DocumentManager.Instance.CurrentDBDocument
uidoc = DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument


def unwrap_single(raw_input):
    if raw_input is None:
        return None
    while isinstance(raw_input, list):
        if len(raw_input) == 0:
            return None
        raw_input = raw_input[0]
    return raw_input


def unwrap_view(raw_input):
    item = unwrap_single(raw_input)
    if not item:
        return None
    if hasattr(item, 'InternalElement'):
        return item.InternalElement
    return item


# --- ВХОДЫ ---
# IN[0] — target_view из Node 3

if IN is None or len(IN) < 1:
    raise Exception("Ошибка: на вход не передан целевой вид.")

target_view = unwrap_view(IN[0])
if not target_view or not isinstance(target_view, View):
    raise Exception("Ошибка: IN[0] не является валидным видом Revit API.")

# --- ШАГ 1: ОЖИДАНИЕ ПЕРЕКЛЮЧЕНИЯ ВИДА ---
view_switched_successfully = False
timeout = 5.0
start_time = time.time()

while uidoc.ActiveView.Id.IntegerValue != target_view.Id.IntegerValue:
    System.Windows.Forms.Application.DoEvents()
    time.sleep(0.05)
    if (time.time() - start_time) > timeout:
        break
else:
    view_switched_successfully = True
    time.sleep(0.15)
    System.Windows.Forms.Application.DoEvents()

if not view_switched_successfully:
    OUT = None
else:
    OUT = doc.GetElement(target_view.Id)
