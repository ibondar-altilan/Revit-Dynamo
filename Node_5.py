# Node 5

# -*- coding: utf-8 -*-
import clr
import math

clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException

clr.AddReference('RevitServices')
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

clr.AddReference('System.Windows.Forms')
import System.Windows.Forms

from System.Collections.Generic import List

doc = DocumentManager.Instance.CurrentDBDocument
uidoc = DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument

_correction_window = None

PARAM_LENGTH = "Длина"
PARAM_CABLE_LENGTH = "Длина проводника"
HORIZ_FAMILY_SUBSTR = "TSL_GM_в_Участок трассы_Горизонтальный"
VERT_FAMILY_NAME = "TSL_GM_в_Участок трассы_Вертикальный"
TRACE_FAMILIES = (HORIZ_FAMILY_SUBSTR, VERT_FAMILY_NAME)


def unwrap_single(raw_input):
    if raw_input is None:
        return None
    while isinstance(raw_input, list):
        if len(raw_input) == 0:
            return None
        raw_input = raw_input[0]
    return raw_input


def get_element_id_value(element_like):
    if element_like is None:
        return None
    try:
        elem_id = element_like.Id
        if elem_id is None:
            return None
        if hasattr(elem_id, 'IntegerValue'):
            return elem_id.IntegerValue
    except Exception:
        pass
    return None


def unwrap_view(raw_input):
    item = unwrap_single(raw_input)
    if not item:
        return None

    for _ in range(3):
        if hasattr(item, 'InternalElement'):
            inner = item.InternalElement
            if inner is None or inner is item:
                break
            item = inner
        else:
            break

    if hasattr(item, 'ToRevitType'):
        try:
            item = item.ToRevitType()
        except Exception:
            pass

    if hasattr(item, 'ViewType') and hasattr(item, 'Id'):
        return item

    id_value = get_element_id_value(item)
    if id_value is not None:
        resolved = doc.GetElement(ElementId(id_value))
        if resolved is not None and hasattr(resolved, 'ViewType'):
            return resolved

    return None


def is_revit_view(candidate):
    if candidate is None:
        return False
    try:
        if hasattr(candidate, 'ViewType') and hasattr(candidate, 'Id'):
            return True
    except Exception:
        pass
    try:
        return candidate.GetType().IsSubclassOf(View)
    except Exception:
        return False


def get_revit_element(dynamo_element):
    item = unwrap_single(dynamo_element)
    if not item:
        return None
    if hasattr(item, 'InternalElement'):
        return item.InternalElement
    if hasattr(item, 'Id') and hasattr(item, 'LookupParameter'):
        return item
    return None


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


def get_family_name(element):
    try:
        symbol = doc.GetElement(element.GetTypeId())
        if symbol is None:
            return ""
        family = symbol.Family
        if family is None:
            return ""
        return family.Name or ""
    except Exception:
        return ""


def is_trace_element(element):
    family_name = get_family_name(element)
    if not family_name:
        return False
    if family_name == VERT_FAMILY_NAME:
        return True
    return HORIZ_FAMILY_SUBSTR in family_name


def read_length_meters(element):
    param = element.LookupParameter(PARAM_LENGTH)
    if param is None or not param.HasValue:
        return 0.0
    if param.StorageType != StorageType.Double:
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


def select_elements(elements):
    if not elements:
        uidoc.Selection.SetElementIds(List[ElementId]())
        return
    id_list = List[ElementId]()
    for element in elements:
        id_list.Add(element.Id)
    TransactionManager.Instance.ForceCloseTransaction()
    uidoc.Selection.SetElementIds(id_list)


def process_trace_edit(window, uiapp, mode):
    active_uidoc = uiapp.ActiveUIDocument
    if active_uidoc is None:
        return

    active_doc = active_uidoc.Document
    picked_elements = []
    hide_for_pick = mode in ("add_pick", "remove_pick")

    if hide_for_pick:
        window.set_visible(False)

    try:
        if mode in ("add_pick", "remove_pick"):
            prompt = (
                "Укажите участки трассы для добавления. ESC — отмена."
                if mode == "add_pick"
                else "Укажите участки трассы для удаления. ESC — отмена."
            )
            refs = active_uidoc.Selection.PickObjects(ObjectType.Element, prompt)
            for ref in refs:
                element = active_doc.GetElement(ref.ElementId)
                if element is not None and is_trace_element(element):
                    picked_elements.append(element)
            if mode == "add_pick" and not picked_elements:
                System.Windows.Forms.MessageBox.Show(
                    "Среди указанных элементов нет участков трассы.",
                    "Корректировка трассы",
                    System.Windows.Forms.MessageBoxButtons.OK,
                    System.Windows.Forms.MessageBoxIcon.Information,
                )
                return
        elif mode == "add_from_selection":
            for element_id in active_uidoc.Selection.GetElementIds():
                element = active_doc.GetElement(element_id)
                if element is not None and is_trace_element(element):
                    picked_elements.append(element)
        elif mode == "replace_from_selection":
            for element_id in active_uidoc.Selection.GetElementIds():
                element = active_doc.GetElement(element_id)
                if element is not None and is_trace_element(element):
                    picked_elements.append(element)
            if not picked_elements:
                System.Windows.Forms.MessageBox.Show(
                    "В выделении Revit нет участков трассы.",
                    "Корректировка трассы",
                    System.Windows.Forms.MessageBoxButtons.OK,
                    System.Windows.Forms.MessageBoxIcon.Information,
                )
                return
            window.replace_trace_elements(picked_elements)
            return
    except OperationCanceledException:
        return
    except Exception as exc:
        System.Windows.Forms.MessageBox.Show(
            str(exc),
            "Корректировка трассы",
            System.Windows.Forms.MessageBoxButtons.OK,
            System.Windows.Forms.MessageBoxIcon.Warning,
        )
        return
    finally:
        if hide_for_pick:
            window.set_visible(True)

    if mode == "add_pick":
        added = window.add_trace_elements(picked_elements)
        if added == 0 and picked_elements:
            System.Windows.Forms.MessageBox.Show(
                "Выбранные участки уже есть в списке трассы.",
                "Корректировка трассы",
                System.Windows.Forms.MessageBoxButtons.OK,
                System.Windows.Forms.MessageBoxIcon.Information,
            )
    elif mode == "remove_pick":
        removed = window.remove_trace_elements(picked_elements)
        if removed == 0 and picked_elements:
            System.Windows.Forms.MessageBox.Show(
                "Выбранные участки отсутствуют в текущей трассе.",
                "Корректировка трассы",
                System.Windows.Forms.MessageBoxButtons.OK,
                System.Windows.Forms.MessageBoxIcon.Information,
            )
    elif mode == "add_from_selection":
        added = window.add_trace_elements(picked_elements)
        if added == 0:
            System.Windows.Forms.MessageBox.Show(
                "В выделении нет новых участков трассы.",
                "Корректировка трассы",
                System.Windows.Forms.MessageBoxButtons.OK,
                System.Windows.Forms.MessageBoxIcon.Information,
            )


def show_message(text, icon=None):
    if icon is None:
        icon = System.Windows.Forms.MessageBoxIcon.Information
    System.Windows.Forms.MessageBox.Show(
        text,
        "Корректировка трассы",
        System.Windows.Forms.MessageBoxButtons.OK,
        icon,
    )


def on_revit_idling(sender, args):
    window = _correction_window
    if window is None or window.pending_mode is None or window.is_finished:
        return

    mode = window.pending_mode
    window.pending_mode = None

    try:
        process_trace_edit(window, sender, mode)
    except Exception as exc:
        System.Windows.Forms.MessageBox.Show(
            str(exc),
            "Корректировка трассы",
            System.Windows.Forms.MessageBoxButtons.OK,
            System.Windows.Forms.MessageBoxIcon.Warning,
        )


def write_cable_length(breaker, length_meters):
    param = breaker.LookupParameter(PARAM_CABLE_LENGTH)
    if param is None:
        raise Exception("Параметр '{0}' не найден на автомате.".format(PARAM_CABLE_LENGTH))
    if param.IsReadOnly:
        raise Exception("Параметр '{0}' доступен только для чтения.".format(PARAM_CABLE_LENGTH))
    if param.StorageType != StorageType.Double:
        raise Exception(
            "Параметр '{0}' должен быть типа Double, получен {1}.".format(
                PARAM_CABLE_LENGTH, param.StorageType
            )
        )

    internal_value = UnitUtils.ConvertToInternalUnits(float(length_meters), UnitTypeId.Meters)
    TransactionManager.Instance.EnsureInTransaction(doc)
    param.Set(internal_value)
    TransactionManager.Instance.TransactionTaskDone()


class TraceCorrectionForm(System.Windows.Forms.Form):
    def __init__(self, trace_elements, breaker_element):
        self.trace_elements = list(trace_elements)
        self.breaker_element = breaker_element
        self.pending_mode = None
        self.result_message = "Отменено пользователем."
        self.is_finished = False
        self.needs_refresh = False
        self.pending_visible = None

        self.Text = "Корректировка трассы и длина проводника"
        self.Width = 540
        self.Height = 420
        self.FormBorderStyle = System.Windows.Forms.FormBorderStyle.FixedDialog
        self.StartPosition = System.Windows.Forms.FormStartPosition.CenterScreen
        self.TopMost = True
        self.MaximizeBox = False
        self.MinimizeBox = False

        margin_x = 15
        content_width = 510
        y = 15

        self.info_label = System.Windows.Forms.Label()
        self.info_label.Left = margin_x
        self.info_label.Top = y
        self.info_label.Width = content_width
        self.info_label.Height = 20
        self.info_label.AutoSize = False
        self.Controls.Add(self.info_label)
        y += 28

        self.length_label = System.Windows.Forms.Label()
        self.length_label.Left = margin_x
        self.length_label.Top = y
        self.length_label.Width = content_width
        self.length_label.Height = 24
        self.Controls.Add(self.length_label)
        y += 36

        hint_label = System.Windows.Forms.Label()
        hint_label.Left = margin_x
        hint_label.Top = y
        hint_label.Width = content_width
        hint_label.Height = 40
        hint_label.Text = (
            "Добавьте или удалите участки кнопками ниже. "
            "Revit перейдёт в режим указания элементов. ESC отменяет выбор."
        )
        self.Controls.Add(hint_label)
        y += 48

        button_height = 34
        button_gap = 8

        self.add_button = System.Windows.Forms.Button()
        self.add_button.Left = margin_x
        self.add_button.Top = y
        self.add_button.Width = content_width
        self.add_button.Height = button_height
        self.add_button.Text = "Добавить участок"
        self.Controls.Add(self.add_button)
        y += button_height + button_gap

        self.remove_button = System.Windows.Forms.Button()
        self.remove_button.Left = margin_x
        self.remove_button.Top = y
        self.remove_button.Width = content_width
        self.remove_button.Height = button_height
        self.remove_button.Text = "Удалить участок"
        self.Controls.Add(self.remove_button)
        y += button_height + button_gap

        self.refresh_button = System.Windows.Forms.Button()
        self.refresh_button.Left = margin_x
        self.refresh_button.Top = y
        self.refresh_button.Width = content_width
        self.refresh_button.Height = button_height
        self.refresh_button.Text = "Заменить список текущим выделением"
        self.Controls.Add(self.refresh_button)
        y += button_height + button_gap

        self.save_button = System.Windows.Forms.Button()
        self.save_button.Left = margin_x
        self.save_button.Top = y
        self.save_button.Width = content_width
        self.save_button.Height = button_height
        self.save_button.Text = "Записать длину и закрыть"
        self.Controls.Add(self.save_button)
        y += button_height + button_gap

        self.cancel_button = System.Windows.Forms.Button()
        self.cancel_button.Left = margin_x
        self.cancel_button.Top = y
        self.cancel_button.Width = content_width
        self.cancel_button.Height = button_height
        self.cancel_button.Text = "Отмена"
        self.Controls.Add(self.cancel_button)

        self.update_display()

    def request_refresh(self):
        self.needs_refresh = True

    def apply_pending_ui(self):
        if self.pending_visible is not None:
            self.Visible = self.pending_visible
            if self.pending_visible:
                self.BringToFront()
            self.pending_visible = None
        if self.needs_refresh:
            self.needs_refresh = False
            self.update_display()

    def set_visible(self, visible):
        self.pending_visible = visible

    def get_trace_id_set(self):
        return set(element.Id.IntegerValue for element in self.trace_elements)

    def add_trace_elements(self, elements):
        existing_ids = self.get_trace_id_set()
        to_add = []
        for element in elements:
            if element.Id.IntegerValue not in existing_ids:
                to_add.append(element)
                existing_ids.add(element.Id.IntegerValue)
        if not to_add:
            return 0
        self.trace_elements.extend(to_add)
        select_elements(self.trace_elements)
        self.request_refresh()
        return len(to_add)

    def remove_trace_elements(self, elements):
        remove_ids = set(element.Id.IntegerValue for element in elements)
        to_remove = [
            element
            for element in self.trace_elements
            if element.Id.IntegerValue in remove_ids
        ]
        if not to_remove:
            return 0
        self.trace_elements = [
            element
            for element in self.trace_elements
            if element.Id.IntegerValue not in remove_ids
        ]
        select_elements(self.trace_elements)
        self.request_refresh()
        return len(to_remove)

    def update_display(self):
        raw_length = calculate_total_length_meters(self.trace_elements)
        rounded_length = ceil_meters(raw_length)
        self.info_label.Text = "Участков трассы: {0}".format(len(self.trace_elements))
        self.length_label.Text = (
            "Длина: {0:.2f} м -> запись: {1} м (округление вверх)".format(
                raw_length, rounded_length
            )
        )

    def replace_trace_elements(self, new_elements):
        self.trace_elements = list(new_elements)
        select_elements(self.trace_elements)
        self.request_refresh()

    def request_edit(self, mode):
        self.pending_mode = mode

    def finish(self, message):
        self.result_message = message
        self.is_finished = True
        self.Close()


def wire_form_events(form):
    def on_add_click(sender, e):
        form.request_edit("add_pick")

    def on_remove_click(sender, e):
        form.request_edit("remove_pick")

    def on_refresh_click(sender, e):
        form.request_edit("replace_from_selection")

    def on_save_click(sender, e):
        if not form.trace_elements:
            show_message(
                "Список трасс пуст. Запись невозможна.",
                System.Windows.Forms.MessageBoxIcon.Warning,
            )
            return
        try:
            final_length = ceil_meters(calculate_total_length_meters(form.trace_elements))
            write_cable_length(form.breaker_element, final_length)
            form.finish(
                "успешно: записано {0} м в '{1}'".format(final_length, PARAM_CABLE_LENGTH)
            )
        except Exception as exc:
            form.finish("ошибка записи: {0}".format(str(exc)))

    def on_cancel_click(sender, e):
        form.finish("Отменено пользователем.")

    def on_closed(sender, e):
        if not form.is_finished:
            form.result_message = "Окно закрыто без записи."
        form.is_finished = True

    form.add_button.Click += on_add_click
    form.remove_button.Click += on_remove_click
    form.refresh_button.Click += on_refresh_click
    form.save_button.Click += on_save_click
    form.cancel_button.Click += on_cancel_click
    form.FormClosed += on_closed


# --- ВХОДЫ ---
# IN[0] — активный вид из Node 4
# IN[1] — список трасс из Node 1
# IN[2] — исходный автомат (2D-выключатель)

if IN is None or len(IN) < 3:
    raise Exception("Ошибка: Недостаточно входных данных для Node 5.")

active_view = unwrap_view(IN[0])
if not is_revit_view(active_view):
    received_type = "None"
    if IN[0] is not None:
        try:
            item = unwrap_single(IN[0])
            received_type = str(item.GetType().FullName) if item is not None else "None"
        except Exception:
            received_type = str(type(IN[0]))
    raise Exception(
        "Ошибка: IN[0] не является валидным видом Revit API. Получен тип: {0}".format(
            received_type
        )
    )

trace_elements = unwrap_element_list(IN[1])
if not trace_elements:
    raise Exception("Ошибка: IN[1] не содержит участков трассы.")

breaker_element = get_revit_element(IN[2])
if not breaker_element:
    raise Exception("Ошибка: IN[2] не содержит исходный автомат.")


# Выделяем участки трассы на активном виде
select_elements(trace_elements)

TransactionManager.Instance.ForceCloseTransaction()

uiapp = DocumentManager.Instance.CurrentUIApplication

_correction_window = TraceCorrectionForm(trace_elements, breaker_element)
wire_form_events(_correction_window)
uiapp.Idling += on_revit_idling
result_message = "Отменено пользователем."

try:
    _correction_window.Show()
    _correction_window.BringToFront()
    _correction_window.Activate()
    while not _correction_window.is_finished:
        _correction_window.apply_pending_ui()
        System.Windows.Forms.Application.DoEvents()
    result_message = _correction_window.result_message
finally:
    try:
        uiapp.Idling -= on_revit_idling
    except Exception:
        pass
    _correction_window = None

OUT = result_message