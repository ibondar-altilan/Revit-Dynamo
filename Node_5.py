# Node 5
# Назначение:
# 1) На плане выделяет найденные участки трассы и считает их длину.
# 2) Показывает окно выбора действия (запись длины или переход к редактированию).
# 3) По кнопке записывает длину в параметр автомата либо завершает без записи.

# -*- coding: utf-8 -*-
import clr
import math
import time

clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *

clr.AddReference('RevitServices')
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')
import System.Windows.Forms

from System.Collections.Generic import List

doc = DocumentManager.Instance.CurrentDBDocument

PARAM_LENGTH = "Длина"
PARAM_CABLE_LENGTH = "Длина проводника"
PARAM_CIRCUIT_NUMBER = "Номер цепи"


def get_uidoc():
    return DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument


def unwrap_single(raw_input):
    if raw_input is None:
        return None
    while isinstance(raw_input, list):
        if len(raw_input) == 0:
            return None
        raw_input = raw_input[0]
    return raw_input


def get_revit_element(dynamo_element):
    item = unwrap_single(dynamo_element)
    if not item:
        return None
    if hasattr(item, 'InternalElement'):
        return item.InternalElement
    if hasattr(item, 'Id') and hasattr(item, 'LookupParameter'):
        return item
    return None


def unwrap_view(raw_input):
    item = unwrap_single(raw_input)
    if not item:
        return None
    if hasattr(item, 'InternalElement'):
        return item.InternalElement
    return item


def is_revit_view(candidate):
    return candidate is not None and isinstance(candidate, View)


def unwrap_element_list(raw_input):
    if raw_input is None:
        return []
    if not isinstance(raw_input, list):
        raw_input = [raw_input]
    result = []
    for item in raw_input:
        element = get_revit_element(item)
        if element is not None:
            result.append(element)
    return result


def get_parameter_value_string(element, param_name):
    param = element.LookupParameter(param_name)
    if not param or not param.HasValue:
        return ""
    if param.StorageType == StorageType.String:
        return param.AsString() or ""
    return param.AsValueString() or ""


def read_length_meters(element):
    param = element.LookupParameter(PARAM_LENGTH)
    if param is None or not param.HasValue or param.StorageType != StorageType.Double:
        return 0.0
    try:
        return UnitUtils.ConvertFromInternalUnits(param.AsDouble(), UnitTypeId.Meters)
    except Exception:
        return param.AsDouble() * 0.3048


def calculate_total_length_meters(elements):
    total = 0.0
    for element in elements:
        total += read_length_meters(element)
    return total


def ceil_meters(value):
    if value <= 0.0:
        return 0
    return int(math.ceil(value - 1e-9))


def select_elements(active_uidoc, elements):
    ids = List[ElementId]()
    for element in elements:
        ids.Add(element.Id)
    active_uidoc.Selection.SetElementIds(ids)


def wait_for_active_view(active_uidoc, target_view, timeout_sec=5.0):
    target_id = target_view.Id.IntegerValue
    start = time.time()
    while active_uidoc.ActiveView.Id.IntegerValue != target_id:
        System.Windows.Forms.Application.DoEvents()
        time.sleep(0.05)
        if time.time() - start > timeout_sec:
            raise Exception(
                "Ошибка: активный вид '{0}' не совпал с планом '{1}' за {2} с.".format(
                    active_uidoc.ActiveView.Name, target_view.Name, timeout_sec
                )
            )


def write_cable_length(breaker, length_meters):
    # Параметр "Число": целые метры без конвертации в футы.
    length_int = ceil_meters(length_meters)
    param = breaker.LookupParameter(PARAM_CABLE_LENGTH)
    if param is None:
        raise Exception("Параметр '{0}' не найден на автомате.".format(PARAM_CABLE_LENGTH))
    if param.IsReadOnly:
        raise Exception("Параметр '{0}' доступен только для чтения.".format(PARAM_CABLE_LENGTH))

    TransactionManager.Instance.EnsureInTransaction(doc)
    if param.StorageType == StorageType.Integer:
        param.Set(length_int)
    elif param.StorageType == StorageType.Double:
        param.Set(float(length_int))
    else:
        raise Exception(
            "Параметр '{0}' должен быть типа Число (Double/Integer), получен {1}.".format(
                PARAM_CABLE_LENGTH, param.StorageType
            )
        )
    TransactionManager.Instance.TransactionTaskDone()


class ActionChoiceForm(System.Windows.Forms.Form):
    def __init__(self, circuit_number, length_meters_rounded):
        self.action = "cancel"
        self.is_finished = False

        self.Text = "Действие с трассой"
        self.Width = 500
        self.Height = 250
        self.StartPosition = System.Windows.Forms.FormStartPosition.CenterScreen
        self.TopMost = True
        self.FormBorderStyle = System.Windows.Forms.FormBorderStyle.FixedDialog
        self.MaximizeBox = False
        self.MinimizeBox = False

        margin_x = 15
        width = 450
        y = 15

        title = System.Windows.Forms.Label()
        title.Left = margin_x
        title.Top = y
        title.Width = width
        title.Height = 45
        title.Text = (
            "Цепь: {0}\r\n"
            "Расчетная длина трассы к записи: {1} м\r\n"
            "Можно перейти на вид Revit для zoom/pan и проверки трассы.".format(
                circuit_number, length_meters_rounded
            )
        )
        self.Controls.Add(title)
        y += 70

        btn_write = System.Windows.Forms.Button()
        btn_write.Left = margin_x
        btn_write.Top = y
        btn_write.Width = width
        btn_write.Height = 35
        btn_write.Text = "Записать расчетную длину трассы"
        btn_write.Click += self.on_write
        self.Controls.Add(btn_write)
        y += 43

        btn_edit = System.Windows.Forms.Button()
        btn_edit.Left = margin_x
        btn_edit.Top = y
        btn_edit.Width = width
        btn_edit.Height = 35
        btn_edit.Text = "Перейти к редактированию трассы"
        btn_edit.Click += self.on_edit
        self.Controls.Add(btn_edit)

        self.FormClosed += self.on_closed

    def on_write(self, sender, e):
        self.action = "write"
        self.is_finished = True
        self.Close()

    def on_edit(self, sender, e):
        self.action = "edit"
        self.is_finished = True
        self.Close()

    def on_closed(self, sender, e):
        self.is_finished = True


# --- ВХОДЫ ---
# IN[0] — активный вид из Node 4
# IN[1] — список трасс из Node 1
# IN[2] — исходный автомат (2D-выключатель)

if IN is None or len(IN) < 3:
    raise Exception("Ошибка: Недостаточно входных данных для Node 5.")

active_view = unwrap_view(IN[0])
if not is_revit_view(active_view):
    raise Exception("Ошибка: IN[0] не является валидным видом Revit API.")

trace_elements = unwrap_element_list(IN[1])
if not trace_elements:
    raise Exception("Ошибка: IN[1] не содержит участков трассы.")

breaker_element = get_revit_element(IN[2])
if not breaker_element:
    raise Exception("Ошибка: IN[2] не содержит исходный автомат.")

circuit_number = get_parameter_value_string(breaker_element, PARAM_CIRCUIT_NUMBER).strip() or "—"
raw_length = calculate_total_length_meters(trace_elements)
rounded_length = ceil_meters(raw_length)

active_uidoc = get_uidoc()
if active_uidoc is None:
    raise Exception("Ошибка: нет активного UIDocument.")

wait_for_active_view(active_uidoc, active_view)
TransactionManager.Instance.ForceCloseTransaction()
select_elements(active_uidoc, trace_elements)

form = ActionChoiceForm(circuit_number, rounded_length)
form.Show()

while not form.is_finished:
    System.Windows.Forms.Application.DoEvents()
    time.sleep(0.02)

if form.action == "write":
    try:
        # Перед записью оставляем рабочее выделение на виде.
        select_elements(active_uidoc, trace_elements)
        write_cable_length(breaker_element, rounded_length)
        OUT = "успешно: записано {0} м в '{1}'".format(rounded_length, PARAM_CABLE_LENGTH)
    except Exception as exc:
        OUT = "ошибка записи: {0}".format(str(exc))
elif form.action == "edit":
    # Вид и выделение уже оставлены активными для ручного редактирования.
    OUT = "режим редактирования: вид и выделение оставлены активными"
else:
    OUT = "Отменено пользователем."
