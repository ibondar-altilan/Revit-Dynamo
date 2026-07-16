# Node 2a (Этап 1)
# Назначение:
# 1) Получает автомат из IN[2].
# 2) По номеру цепи автомата находит объект ElectricalSystem.
# 3) Получает список потребителей цепи и сразу отдает его в OUT.

# -*- coding: utf-8 -*-
import clr
import math

clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Electrical import ElectricalSystem
clr.AddReference('RevitAPIUI')
from Autodesk.Revit.UI import *

clr.AddReference('RevitServices')
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')
import System.Windows.Forms
import System.Drawing

doc = DocumentManager.Instance.CurrentDBDocument
PARAM_MAX_CABLE_LENGTH = "Длина проводника до дальнего устройства"


def unwrap_dynamo_input(value):
    """Распаковка вложенных списков Dynamo и оберток элементов."""
    raw = value
    while isinstance(raw, list):
        if len(raw) == 0:
            return None
        raw = raw[0]
    if hasattr(raw, "InternalElement"):
        return raw.InternalElement
    return raw


def unwrap_dynamo_list(value):
    """Возвращает плоский список элементов из входа Dynamo."""
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    result = []
    for item in value:
        if isinstance(item, list):
            for nested in item:
                unwrapped = unwrap_dynamo_input(nested)
                if unwrapped is not None:
                    result.append(unwrapped)
        else:
            unwrapped = unwrap_dynamo_input(item)
            if unwrapped is not None:
                result.append(unwrapped)
    return result


def get_parameter_value_string(element, param_name):
    """Возвращает строковое значение параметра элемента."""
    if not element:
        return ""
    param = element.LookupParameter(param_name)
    if not param or not param.HasValue:
        return ""
    if param.StorageType == StorageType.String:
        return (param.AsString() or "").strip()
    return (param.AsValueString() or "").strip()


def normalize_text(value):
    return (value or "").strip().lower()

# Разрешенные категории потребителей (задаются в скрипте, без чтения файла во время исполнения)
ALLOWED_CONSUMER_CATEGORIES = [
    "Осветительные приборы",
    "Электрические приборы",
    "Специальное оборудование",
    "Электрооборудование",
]
ALLOWED_CONSUMER_CATEGORIES_NORM = set([normalize_text(x) for x in ALLOWED_CONSUMER_CATEGORIES])


# --- ВХОДЫ ---
if IN is None or len(IN) < 5:
    raise Exception(
        "Ошибка: ожидаются входы IN[0], IN[1], IN[2], IN[3], IN[4], IN[5]. "
        "Обязательны IN[2] (автомат), IN[3] (допуск привязки), IN[4] (допуск склейки узлов). "
        "IN[5] обязателен только при графах на нескольких уровнях."
    )

revit_automatic = unwrap_dynamo_input(IN[2])
if revit_automatic is None:
    raise Exception("Ошибка: IN[2] пуст. Передайте выбранный автомат.")

circuit_number = get_parameter_value_string(revit_automatic, "Номер цепи")
if not circuit_number:
    raise Exception("Ошибка: у выбранного автомата пуст параметр 'Номер цепи'.")

target_circuit_number = normalize_text(circuit_number)
input_tolerance_m = IN[3] if len(IN) > 3 else None
if input_tolerance_m is None:
    raise Exception("Ошибка: IN[3] (допуск в метрах) не задан.")

try:
    tolerance_m = float(input_tolerance_m)
except:
    raise Exception("Ошибка: IN[3] должен быть числом (метры).")

if tolerance_m <= 0:
    raise Exception("Ошибка: IN[3] должен быть больше 0.")

input_node_merge_tolerance_m = IN[4] if len(IN) > 4 else None
if input_node_merge_tolerance_m is None:
    raise Exception("Ошибка: IN[4] (допуск склейки узлов в метрах) не задан.")

try:
    node_merge_tolerance_m = float(input_node_merge_tolerance_m)
except:
    raise Exception("Ошибка: IN[4] должен быть числом (метры).")

if node_merge_tolerance_m <= 0:
    raise Exception("Ошибка: IN[4] должен быть больше 0.")

vertical_link_element = unwrap_dynamo_input(IN[5]) if len(IN) > 5 else None

tolerance_ft = tolerance_m * 3.280839895
node_merge_tolerance_ft = node_merge_tolerance_m * 3.280839895


# --- ПОИСК ОБЪЕКТА ELECTRICALSYSTEM ПО НОМЕРУ ЦЕПИ ---
systems = FilteredElementCollector(doc).OfClass(ElectricalSystem).ToElements()

matched_systems = []
for system in systems:
    system_number = normalize_text(system.CircuitNumber)
    if system_number == target_circuit_number:
        matched_systems.append(system)

if len(matched_systems) == 0:
    raise Exception("Ошибка: электрическая цепь с номером '{}' не найдена.".format(circuit_number))

if len(matched_systems) > 1:
    duplicate_ids = [s.Id.IntegerValue for s in matched_systems]
    raise Exception(
        "Ошибка: найдено несколько электрических цепей с номером '{}'. ID цепей: {}"
        .format(circuit_number, duplicate_ids)
    )

target_system = matched_systems[0]


# --- ПОЛУЧЕНИЕ ПОТРЕБИТЕЛЕЙ ЦЕПИ ---
# Эквивалент стандартного узла Dynamo ElectricalSystem.Elements
elements_set = target_system.Elements
consumers = [el for el in elements_set if el is not None]


def get_category_name(element):
    if not element or not hasattr(element, "Category") or element.Category is None:
        return "Без категории"
    return (element.Category.Name or "Без категории").strip()


def get_element_display_name(element):
    if element is None:
        return "Без имени"
    try:
        name_value = element.Name
        if name_value:
            return str(name_value).strip()
    except:
        pass
    return "Элемент"


def get_param_or_no_data(element, param_name):
    value = get_parameter_value_string(element, param_name)
    return value if value else "нет данных"


# Параметры экземпляров для определения уровня (см. файл проекта "Промпт параметров Revit...")
CONSUMER_LEVEL_PARAM_NAMES = [
    "Уровень",               # AsValueString
    "Уровень спецификации",  # AsValueString
]


def get_level_name_or_no_data(element):
    """Определяет уровень потребителя по параметрам проекта."""
    for param_name in CONSUMER_LEVEL_PARAM_NAMES:
        value = get_parameter_value_string(element, param_name)
        if value:
            return value
    # Fallback на старый параметр (если еще используется в проекте)
    legacy = get_parameter_value_string(element, "TSL_Имя уровня")
    return legacy if legacy else "нет данных"


def distance_xy(p1, p2):
    dx = p1[0] - p2[0]
    dy = p1[1] - p2[1]
    return math.sqrt(dx * dx + dy * dy)


def ft_to_m(value_ft):
    return value_ft * 0.3048


def ceil_meters(value_m):
    if value_m <= 0.0:
        return 0
    return int(math.ceil(value_m - 1e-9))


def write_max_length_to_breaker(breaker, length_m_ceil):
    """Записывает длину в параметр автомата 'Длина проводника до дальнего устройства'."""
    param = breaker.LookupParameter(PARAM_MAX_CABLE_LENGTH)
    if param is None:
        raise Exception("Параметр '{}' не найден на автомате.".format(PARAM_MAX_CABLE_LENGTH))
    if param.IsReadOnly:
        raise Exception("Параметр '{}' доступен только для чтения.".format(PARAM_MAX_CABLE_LENGTH))

    TransactionManager.Instance.EnsureInTransaction(doc)
    if param.StorageType == StorageType.Integer:
        param.Set(int(length_m_ceil))
    elif param.StorageType == StorageType.Double:
        param.Set(float(length_m_ceil))
    elif param.StorageType == StorageType.String:
        param.Set(str(length_m_ceil))
    else:
        TransactionManager.Instance.TransactionTaskDone()
        raise Exception(
            "Параметр '{}' имеет неподдерживаемый тип: {}.".format(PARAM_MAX_CABLE_LENGTH, param.StorageType)
        )
    TransactionManager.Instance.TransactionTaskDone()


def show_result_window(message_text, allow_write, is_modal, breaker=None, write_value_m=None):
    """Показывает окно результата (модальное/немодальное)."""
    if not message_text:
        return

    screen = System.Windows.Forms.Screen.FromPoint(System.Windows.Forms.Cursor.Position).WorkingArea
    margin = 16
    button_width = 170 if allow_write else 160
    button_height = 32
    button_spacing = 12
    content_min_width = 420
    content_max_width = int(screen.Width * 0.78)
    max_client_width = int(screen.Width * 0.90)
    max_client_height = int(screen.Height * 0.90)
    text_font = System.Drawing.Font("Segoe UI", 10)
    text_flags = System.Windows.Forms.TextFormatFlags.WordBreak

    probe_size = System.Drawing.Size(content_max_width, 10000)
    measured_probe = System.Windows.Forms.TextRenderer.MeasureText(
        message_text, text_font, probe_size, text_flags
    )
    content_width = measured_probe.Width
    if content_width < content_min_width:
        content_width = content_min_width
    if content_width > content_max_width:
        content_width = content_max_width

    client_width = content_width + margin * 2
    if client_width > max_client_width:
        client_width = max_client_width

    final_content_width = client_width - margin * 2
    measured_final = System.Windows.Forms.TextRenderer.MeasureText(
        message_text, text_font, System.Drawing.Size(final_content_width, 10000), text_flags
    )
    content_height = measured_final.Height + 12
    client_height = margin + content_height + margin + button_height + margin
    if client_height > max_client_height:
        client_height = max_client_height

    form = System.Windows.Forms.Form()
    form.Text = "Результат расчёта трассы"
    form.StartPosition = System.Windows.Forms.FormStartPosition.CenterScreen
    form.TopMost = True
    form.FormBorderStyle = System.Windows.Forms.FormBorderStyle.FixedDialog
    form.MaximizeBox = False
    form.MinimizeBox = False
    form.AutoScaleMode = System.Windows.Forms.AutoScaleMode.Dpi
    form.BackColor = System.Drawing.Color.White
    form.ClientSize = System.Drawing.Size(client_width, client_height)

    text_panel = System.Windows.Forms.Panel()
    text_panel.Left = margin
    text_panel.Top = margin
    text_panel.Width = form.ClientSize.Width - margin * 2
    text_panel.Height = form.ClientSize.Height - margin * 3 - button_height
    text_panel.BackColor = System.Drawing.Color.White
    text_panel.BorderStyle = System.Windows.Forms.BorderStyle.FixedSingle
    text_panel.Anchor = (
        System.Windows.Forms.AnchorStyles.Top
        | System.Windows.Forms.AnchorStyles.Bottom
        | System.Windows.Forms.AnchorStyles.Left
        | System.Windows.Forms.AnchorStyles.Right
    )
    form.Controls.Add(text_panel)

    message_label = System.Windows.Forms.Label()
    message_label.Dock = System.Windows.Forms.DockStyle.Fill
    message_label.AutoSize = False
    message_label.TextAlign = System.Drawing.ContentAlignment.MiddleCenter
    message_label.BackColor = System.Drawing.Color.White
    message_label.ForeColor = System.Drawing.Color.Black
    message_label.Font = text_font
    message_label.Text = message_text
    text_panel.Controls.Add(message_label)

    btn_exit = System.Windows.Forms.Button()
    btn_exit.Text = "Выйти без записи"
    btn_exit.Width = button_width
    btn_exit.Height = button_height
    btn_exit.Top = form.ClientSize.Height - margin - btn_exit.Height
    btn_exit.Anchor = System.Windows.Forms.AnchorStyles.Bottom
    form.Controls.Add(btn_exit)

    btn_write = None
    if allow_write:
        btn_write = System.Windows.Forms.Button()
        btn_write.Text = "Записать"
        btn_write.Width = button_width
        btn_write.Height = button_height
        btn_write.Top = form.ClientSize.Height - margin - btn_write.Height
        btn_write.Anchor = System.Windows.Forms.AnchorStyles.Bottom
        form.Controls.Add(btn_write)
        total_buttons_width = btn_write.Width + button_spacing + btn_exit.Width
        left_start = (form.ClientSize.Width - total_buttons_width) / 2
        btn_write.Left = left_start
        btn_exit.Left = btn_write.Right + button_spacing
    else:
        btn_exit.Left = (form.ClientSize.Width - btn_exit.Width) / 2

    if is_modal:
        btn_exit.DialogResult = System.Windows.Forms.DialogResult.Cancel
        form.CancelButton = btn_exit
        if allow_write and btn_write is not None:
            btn_write.DialogResult = System.Windows.Forms.DialogResult.OK
            form.AcceptButton = btn_write
        else:
            form.AcceptButton = btn_exit

        dialog_result = form.ShowDialog()
        if allow_write and dialog_result == System.Windows.Forms.DialogResult.OK:
            if breaker is None or write_value_m is None:
                raise Exception("Нет данных для записи.")
            write_max_length_to_breaker(breaker, write_value_m)
            System.Windows.Forms.MessageBox.Show(
                "Записано {0} м в параметр '{1}'.".format(write_value_m, PARAM_MAX_CABLE_LENGTH),
                "Запись длины",
                System.Windows.Forms.MessageBoxButtons.OK,
                System.Windows.Forms.MessageBoxIcon.Information
            )
        return

    # Немодальный режим (при неуспешном расчете, без записи)
    def on_exit_click(sender, args):
        form.Close()

    btn_exit.Click += on_exit_click
    if btn_write is not None:
        btn_write.Enabled = False
    form.Show()


def get_element_xy_point(element):
    """Получение опорной XY-точки элемента (Z игнорируется)."""
    if element is None:
        return None

    location = element.Location
    if location:
        if hasattr(location, "Point") and location.Point is not None:
            return (location.Point.X, location.Point.Y)
        if hasattr(location, "Curve") and location.Curve is not None:
            c = location.Curve
            p0 = c.GetEndPoint(0)
            p1 = c.GetEndPoint(1)
            return ((p0.X + p1.X) / 2.0, (p0.Y + p1.Y) / 2.0)

    return None


# --- ФИЛЬТРАЦИЯ ПОТРЕБИТЕЛЕЙ ПО РАЗРЕШЕННЫМ КАТЕГОРИЯМ ---
allowed_consumers = []
for consumer in consumers:
    cat_name = get_category_name(consumer)
    if normalize_text(cat_name) in ALLOWED_CONSUMER_CATEGORIES_NORM:
        allowed_consumers.append(consumer)


# --- ПРОВЕРКА ЩИТА ПО ПАРАМЕТРУ "ПРИНАДЛЕЖНОСТЬ ЩИТУ" ---
panel_name_from_automatic = get_parameter_value_string(revit_automatic, "Принадлежность щиту")
if not panel_name_from_automatic:
    raise Exception("Ошибка: у выбранного автомата пуст параметр 'Принадлежность щиту'.")

electrical_equipment = (
    FilteredElementCollector(doc)
    .OfCategory(BuiltInCategory.OST_ElectricalEquipment)
    .WhereElementIsNotElementType()
    .ToElements()
)

matched_panels = []
for equip in electrical_equipment:
    panel_name = get_parameter_value_string(equip, "Имя панели")
    if normalize_text(panel_name) == normalize_text(panel_name_from_automatic):
        matched_panels.append(equip)

if len(matched_panels) == 0:
    raise Exception(
        "Ошибка: щит с параметром 'Имя панели' = '{}' не найден."
        .format(panel_name_from_automatic)
    )

if len(matched_panels) > 1:
    duplicate_panel_ids = [panel.Id.IntegerValue for panel in matched_panels]
    raise Exception(
        "Ошибка: найдено несколько щитов с 'Имя панели' = '{}'. Дублирующиеся ID: {}"
        .format(panel_name_from_automatic, duplicate_panel_ids)
    )

panel = matched_panels[0]


# --- ПОЛУЧЕНИЕ УЧАСТКОВ ИЗ IN[0] ---
raw_sections = IN[0] if len(IN) > 0 else None
sections = unwrap_dynamo_list(raw_sections)

# Точные имена семейств (по аналогии с Node_1)
HORIZONTAL_FAMILY_NAMES = [
    "TSL_GM_в_Участок трассы_Горизонтальный",
]
VERTICAL_FAMILY_NAMES = [
    "TSL_GM_в_Участок трассы_Вертикальный",
]

horizontal_sections = []
vertical_sections = []
for sec in sections:
    if not hasattr(sec, "Symbol") or sec.Symbol is None or sec.Symbol.Family is None:
        continue
    family_name = sec.Symbol.Family.Name or ""
    family_name_norm = normalize_text(family_name)
    is_horizontal = family_name_norm in [normalize_text(x) for x in HORIZONTAL_FAMILY_NAMES]
    is_vertical = family_name_norm in [normalize_text(x) for x in VERTICAL_FAMILY_NAMES]
    if not is_horizontal and not is_vertical:
        continue

    location = sec.Location
    if not location:
        continue

    # Горизонтальные участки ожидаются как кривые
    if is_horizontal:
        if not hasattr(location, "Curve") or location.Curve is None:
            continue
        curve = location.Curve
        section_data = {
            "element": sec,
            "id": sec.Id.IntegerValue,
            "length_ft": curve.Length,
            "p0_xy": (curve.GetEndPoint(0).X, curve.GetEndPoint(0).Y),
            "p1_xy": (curve.GetEndPoint(1).X, curve.GetEndPoint(1).Y),
            "level_name": get_level_name_or_no_data(sec)
        }
        horizontal_sections.append(section_data)

    # Вертикальные могут быть как Curve, так и Point (одна координата)
    if is_vertical:
        if hasattr(location, "Curve") and location.Curve is not None:
            curve = location.Curve
            section_data = {
                "element": sec,
                "id": sec.Id.IntegerValue,
                "length_ft": curve.Length,
                "p0_xy": (curve.GetEndPoint(0).X, curve.GetEndPoint(0).Y),
                "p1_xy": (curve.GetEndPoint(1).X, curve.GetEndPoint(1).Y),
                "level_name": get_level_name_or_no_data(sec)
            }
            vertical_sections.append(section_data)
        elif hasattr(location, "Point") and location.Point is not None:
            pt = location.Point
            # Для точечного размещения длину пробуем взять из параметра "Длина", иначе 0.
            length_param = sec.LookupParameter("Длина")
            length_ft = 0.0
            if length_param and length_param.HasValue:
                try:
                    if length_param.StorageType == StorageType.Double:
                        length_ft = length_param.AsDouble()
                    else:
                        length_ft = float(length_param.AsValueString())
                except:
                    length_ft = 0.0
            section_data = {
                "element": sec,
                "id": sec.Id.IntegerValue,
                "length_ft": length_ft,
                "p0_xy": (pt.X, pt.Y),
                "p1_xy": (pt.X, pt.Y),
                "level_name": get_level_name_or_no_data(sec)
            }
            vertical_sections.append(section_data)

if not horizontal_sections:
    raise Exception("Ошибка: в IN[0] не найдено горизонтальных участков трассы.")

# --- ПОСТРОЕНИЕ 2D ГРАФОВ ТРАССЫ ПО УРОВНЯМ (ТОЛЬКО XY) ---
graph_nodes = []  # [(x, y), ...]
graph_edges = []  # [{"id","element","length_ft","n1","n2"}, ...]
adjacency = {}    # node_index -> [edge_index, ...]
node_source_points = {}  # node_index -> [(x, y), ...] исходные точки, попавшие в узел
node_level_by_index = {}  # node_index -> level_name
level_to_graph_nodes = {}  # level_name -> [node_index, ...]

sections_by_level = {}
for sec in horizontal_sections:
    lvl = sec.get("level_name", "нет данных")
    if lvl not in sections_by_level:
        sections_by_level[lvl] = []
    sections_by_level[lvl].append(sec)

levels_with_graph = sorted(sections_by_level.keys(), key=lambda x: normalize_text(x))

for level_name in levels_with_graph:
    level_sections = sections_by_level[level_name]
    local_nodes = []
    local_source_points = {}

    def get_or_create_local_node_index(pt_xy):
        nearest_idx = None
        nearest_dist = None
        for idx, node_pt in enumerate(local_nodes):
            d = distance_xy(pt_xy, node_pt)
            if d <= node_merge_tolerance_ft:
                if nearest_dist is None or d < nearest_dist:
                    nearest_dist = d
                    nearest_idx = idx
        if nearest_idx is not None:
            local_source_points[nearest_idx].append(pt_xy)
            return nearest_idx
        local_nodes.append(pt_xy)
        new_idx = len(local_nodes) - 1
        local_source_points[new_idx] = [pt_xy]
        return new_idx

    local_edges = []
    for section in level_sections:
        ln1 = get_or_create_local_node_index(section["p0_xy"])
        ln2 = get_or_create_local_node_index(section["p1_xy"])
        if ln1 == ln2:
            local_nodes.append(section["p1_xy"])
            ln2 = len(local_nodes) - 1
            local_source_points[ln2] = [section["p1_xy"]]
        local_edges.append({
            "section": section,
            "ln1": ln1,
            "ln2": ln2
        })

    local_to_global = {}
    for ln_idx, pt_xy in enumerate(local_nodes):
        g_idx = len(graph_nodes)
        graph_nodes.append(pt_xy)
        adjacency[g_idx] = []
        node_source_points[g_idx] = list(local_source_points.get(ln_idx, [pt_xy]))
        node_level_by_index[g_idx] = level_name
        local_to_global[ln_idx] = g_idx
        if level_name not in level_to_graph_nodes:
            level_to_graph_nodes[level_name] = []
        level_to_graph_nodes[level_name].append(g_idx)

    for edge_item in local_edges:
        section = edge_item["section"]
        n1 = local_to_global[edge_item["ln1"]]
        n2 = local_to_global[edge_item["ln2"]]
        edge_data = {
            "id": section["id"],
            "element": section["element"],
            "length_ft": section["length_ft"],
            "p0_xy": section["p0_xy"],
            "p1_xy": section["p1_xy"],
            "n1": n1,
            "n2": n2,
            "level_name": level_name
        }
        graph_edges.append(edge_data)
        edge_index = len(graph_edges) - 1
        adjacency[n1].append(edge_index)
        adjacency[n2].append(edge_index)


if len(levels_with_graph) > 1:
    if vertical_link_element is None:
        OUT = ["Нет точки вертикальной связности"]
        raise Exception("Нет точки вертикальной связности")

    vertical_link_xy = get_element_xy_point(vertical_link_element)
    if vertical_link_xy is None:
        OUT = ["Нет точки вертикальной связности"]
        raise Exception("Нет точки вертикальной связности")

    level_link_nodes = {}
    missing_levels = []
    for level_name in levels_with_graph:
        candidate_nodes = level_to_graph_nodes.get(level_name, [])
        nearest_node = None
        nearest_dist = None
        for node_idx in candidate_nodes:
            d = distance_xy(vertical_link_xy, graph_nodes[node_idx])
            if nearest_dist is None or d < nearest_dist:
                nearest_dist = d
                nearest_node = node_idx

        if nearest_node is None or nearest_dist > tolerance_ft:
            missing_levels.append(level_name)
        else:
            level_link_nodes[level_name] = nearest_node

    if missing_levels:
        missing_text = ", ".join(missing_levels)
        OUT = ["Ошибка: нет узла для вертикальной связности на уровне: {}".format(missing_text)]
        raise Exception("Ошибка вертикальной связности по уровням: {}".format(missing_text))

    base_level = levels_with_graph[0]
    base_node = level_link_nodes[base_level]
    for level_name in levels_with_graph[1:]:
        target_node = level_link_nodes[level_name]
        if target_node == base_node:
            continue
        link_edge = {
            "id": "VLINK_{}_{}".format(base_level, level_name),
            "element": vertical_link_element,
            "length_ft": 0.0,
            "p0_xy": graph_nodes[base_node],
            "p1_xy": graph_nodes[target_node],
            "n1": base_node,
            "n2": target_node,
            "level_name": "Межуровневый",
            "virtual_vertical_link": True
        }
        graph_edges.append(link_edge)
        link_edge_idx = len(graph_edges) - 1
        adjacency[base_node].append(link_edge_idx)
        adjacency[target_node].append(link_edge_idx)


def find_nearest_node_within_tolerance(pt_xy):
    nearest_node = None
    nearest_dist = None
    for idx, node_pt in enumerate(graph_nodes):
        d = distance_xy(pt_xy, node_pt)
        if nearest_dist is None or d < nearest_dist:
            nearest_dist = d
            nearest_node = idx
    if nearest_dist is None or nearest_dist > tolerance_ft:
        return None
    return nearest_node


node_match_points = None


def find_nodes_within_tolerance(pt_xy):
    """Возвращает все узлы графа в пределах допуска привязки к потребителю."""
    result = []
    for idx in range(len(graph_nodes)):
        node_pt = graph_nodes[idx]
        if node_match_points is not None and idx < len(node_match_points) and node_match_points[idx] is not None:
            node_pt = node_match_points[idx]
        d = distance_xy(pt_xy, node_pt)
        if d <= tolerance_ft:
            result.append({
                "node_idx": idx,
                "dist_xy_ft": d
            })
    return result


def get_nearest_node_debug(pt_xy):
    """Ближайший узел графа для отладки (индекс, дистанция, координаты)."""
    nearest_idx = None
    nearest_dist = None
    nearest_pt = None
    for idx in range(len(graph_nodes)):
        node_pt = graph_nodes[idx]
        if node_match_points is not None and idx < len(node_match_points) and node_match_points[idx] is not None:
            node_pt = node_match_points[idx]
        d = distance_xy(pt_xy, node_pt)
        if nearest_dist is None or d < nearest_dist:
            nearest_dist = d
            nearest_idx = idx
            nearest_pt = node_pt
    if nearest_idx is None:
        return None
    return {
        "node_idx": nearest_idx,
        "dist_ft": nearest_dist,
        "node_pt": nearest_pt
    }


def get_nearest_node_distance_xy(pt_xy):
    """Минимальная XY-дистанция от точки до любого узла графа."""
    nearest_dist = None
    for node_pt in graph_nodes:
        d = distance_xy(pt_xy, node_pt)
        if nearest_dist is None or d < nearest_dist:
            nearest_dist = d
    return nearest_dist


def get_section_point_distance_xy(section_data, pt_xy):
    d1 = distance_xy(section_data["p0_xy"], pt_xy)
    d2 = distance_xy(section_data["p1_xy"], pt_xy)
    return min(d1, d2)


def get_nearest_vertical_section_near_point(pt_xy, excluded_ids):
    nearest_section = None
    nearest_dist = None
    for sec_data in vertical_sections:
        if sec_data["id"] in excluded_ids:
            continue
        d = get_section_point_distance_xy(sec_data, pt_xy)
        if d <= tolerance_ft and (nearest_dist is None or d < nearest_dist):
            nearest_dist = d
            nearest_section = sec_data
    return nearest_section


panel_xy = get_element_xy_point(panel)
if panel_xy is None:
    raise Exception("Ошибка: не удалось определить XY-координаты щита '{}'.".format(panel_name_from_automatic))

start_node = find_nearest_node_within_tolerance(panel_xy)
if start_node is None:
    raise Exception(
        "Трасса {} не подключена к щиту {}".format(circuit_number, panel_name_from_automatic)
    )


# --- ПОИСК КРАТЧАЙШИХ ПУТЕЙ ОТ ЩИТА ДО ВСЕХ УЗЛОВ ГРАФА ---
dist = {}
prev_edge = {}
visited = set()
for i in range(len(graph_nodes)):
    dist[i] = float("inf")
    prev_edge[i] = None
dist[start_node] = 0.0

while True:
    current = None
    current_dist = float("inf")
    for i in range(len(graph_nodes)):
        if i in visited:
            continue
        if dist[i] < current_dist:
            current_dist = dist[i]
            current = i

    if current is None:
        break

    visited.add(current)

    for edge_idx in adjacency.get(current, []):
        edge = graph_edges[edge_idx]
        neighbor = edge["n2"] if edge["n1"] == current else edge["n1"]
        if neighbor in visited:
            continue
        candidate = dist[current] + edge["length_ft"]
        if candidate < dist[neighbor]:
            dist[neighbor] = candidate
            prev_edge[neighbor] = edge_idx


def restore_path_edges(target_node):
    """Возвращает список edge_index от щита к целевому узлу."""
    if dist.get(target_node, float("inf")) == float("inf"):
        return None

    result = []
    current = target_node
    while current != start_node:
        edge_idx = prev_edge.get(current)
        if edge_idx is None:
            return None
        result.append(edge_idx)
        edge = graph_edges[edge_idx]
        current = edge["n1"] if edge["n2"] == current else edge["n2"]
    result.reverse()
    return result


def build_node_match_points_towards_panel():
    """
    Возвращает координаты узлов для привязки потребителей.
    Для каждого узла берем точку на ребре, ведущем к щиту по prev_edge.
    Это сохраняет "приходящий к потребителю" участок при склейке узлов по допуску.
    """
    match_points = []
    for node_idx in range(len(graph_nodes)):
        source_points = node_source_points.get(node_idx, [graph_nodes[node_idx]])
        selected = graph_nodes[node_idx]

        if node_idx == start_node:
            # Для стартового узла берём точку, наиболее близкую к щиту.
            selected = min(source_points, key=lambda p: distance_xy(p, panel_xy))
        else:
            incoming_edge_idx = prev_edge.get(node_idx)
            if incoming_edge_idx is not None:
                incoming_edge = graph_edges[incoming_edge_idx]
                if incoming_edge["n1"] == node_idx:
                    selected = incoming_edge["p0_xy"]
                else:
                    selected = incoming_edge["p1_xy"]
            elif source_points:
                selected = source_points[0]

        match_points.append(selected)
    return match_points


def collect_component_edge_ids(start_node_idx):
    """Собирает ID участков (ребер) связной компоненты узла."""
    pending = [start_node_idx]
    visited_nodes = set()
    visited_edges = set()
    edge_ids = set()
    while pending:
        node_idx = pending.pop()
        if node_idx in visited_nodes:
            continue
        visited_nodes.add(node_idx)
        for edge_idx in adjacency.get(node_idx, []):
            if edge_idx in visited_edges:
                continue
            visited_edges.add(edge_idx)
            edge = graph_edges[edge_idx]
            edge_ids.add(edge["id"])
            neighbor = edge["n2"] if edge["n1"] == node_idx else edge["n1"]
            if neighbor not in visited_nodes:
                pending.append(neighbor)
    return sorted(list(edge_ids))


def get_consumer_connection_to_graph(consumer_xy):
    """
    Привязка потребителя к графу:
    - выбираем узлы в пределах допуска;
    - если найдено несколько, берем ближайший к потребителю по XY.
      При равенстве XY используем минимальную дистанцию до щита по графу.
    """
    nearest_node_debug = get_nearest_node_debug(consumer_xy)
    candidate_nodes = find_nodes_within_tolerance(consumer_xy)
    if not candidate_nodes:
        return {
            "status": "no_nodes_in_tolerance",
            "path_edges": None,
            "debug_nearest_node": nearest_node_debug,
            "disconnected_edge_ids": []
        }

    reachable = []
    for item in candidate_nodes:
        node_idx = item["node_idx"]
        d_graph = dist.get(node_idx, float("inf"))
        if d_graph != float("inf"):
            reachable.append({
                "node_idx": node_idx,
                "dist_graph_ft": d_graph,
                "dist_xy_ft": item["dist_xy_ft"]
            })

    if not reachable:
        disconnected_edge_ids = []
        for item in candidate_nodes:
            disconnected_edge_ids.extend(collect_component_edge_ids(item["node_idx"]))
        disconnected_edge_ids = sorted(list(set(disconnected_edge_ids)))
        return {
            "status": "disconnected_from_panel",
            "path_edges": None,
            "debug_nearest_node": nearest_node_debug,
            "disconnected_edge_ids": disconnected_edge_ids
        }

    # Главный критерий: ближайший к потребителю по XY.
    # При равенстве — близость к щиту по графу.
    reachable_sorted = sorted(
        reachable,
        key=lambda x: (x["dist_xy_ft"], x["dist_graph_ft"], x["node_idx"])
    )
    chosen_node = reachable_sorted[0]["node_idx"]

    path_edges = restore_path_edges(chosen_node)
    if path_edges is None and chosen_node != start_node:
        return {
            "status": "disconnected_from_panel",
            "path_edges": None,
            "debug_nearest_node": nearest_node_debug,
            "disconnected_edge_ids": collect_component_edge_ids(chosen_node)
        }

    return {
        "status": "ok",
        "type": "node",
        "path_edges": [] if path_edges is None else path_edges,
        "debug_nearest_node": nearest_node_debug,
        "disconnected_edge_ids": []
    }


def format_nearest_node_debug(debug_info):
    if not debug_info:
        return "нет данных"
    pt = debug_info["node_pt"]
    return (
        "ближайший узел IDx={0}, dist={1:.3f} м, XY=({2:.3f}, {3:.3f}) м"
        .format(
            debug_info["node_idx"],
            ft_to_m(debug_info["dist_ft"]),
            ft_to_m(pt[0]),
            ft_to_m(pt[1])
        )
    )


# --- ФОРМИРОВАНИЕ ОТЧЕТА ПУТЕЙ К ПОТРЕБИТЕЛЯМ ---
node_match_points = build_node_match_points_towards_panel()
output_lines = []
not_found_consumers = []
consumer_reports = []
consumers_sorted = sorted(
    allowed_consumers,
    key=lambda x: (normalize_text(get_element_display_name(x)), x.Id.IntegerValue)
)

for consumer in consumers_sorted:
    consumer_name = get_element_display_name(consumer)
    consumer_id = consumer.Id.IntegerValue
    space_name = get_param_or_no_data(consumer, "TSL_Имя пространства")
    space_number = get_param_or_no_data(consumer, "TSL_Номер пространства")
    level_name = get_level_name_or_no_data(consumer)

    consumer_xy = get_element_xy_point(consumer)
    if consumer_xy is None:
        not_found_consumers.append({
            "name": consumer_name,
            "id": consumer_id,
            "space_name": space_name,
            "space_number": space_number,
            "level_name": level_name,
            "reason": "Не удалось определить координаты потребителя"
        })
        continue

    connection = get_consumer_connection_to_graph(consumer_xy)
    if connection["status"] != "ok":
        disconnected_ids = connection.get("disconnected_edge_ids", [])
        not_found_consumers.append({
            "name": consumer_name,
            "id": consumer_id,
            "space_name": space_name,
            "space_number": space_number,
            "level_name": level_name,
            "reason": "Узел трассы в допуске не найден или не связан со щитом",
            "nearest_node_debug": format_nearest_node_debug(connection.get("debug_nearest_node")),
            "disconnected_edge_ids": disconnected_ids
        })
        continue

    path_edge_indices = connection["path_edges"]
    if path_edge_indices is None:
        not_found_consumers.append({
            "name": consumer_name,
            "id": consumer_id,
            "space_name": space_name,
            "space_number": space_number,
            "level_name": level_name,
            "reason": "Путь от щита до потребителя не найден"
        })
        continue

    report_lines = []
    report_lines.append("--------------------------------------------------")
    report_lines.append("Потребитель: {} (ID {})".format(consumer_name, consumer_id))
    report_lines.append("Маршрут: от потребителя к щиту")
    path_sections = []
    used_section_ids = set()

    # Включаем ближайший вертикальный участок у потребителя (если есть)
    consumer_vertical = get_nearest_vertical_section_near_point(consumer_xy, used_section_ids)
    if consumer_vertical is not None:
        path_sections.append({
            "id": consumer_vertical["id"],
            "length_ft": consumer_vertical["length_ft"],
            "marker": "потребитель"
        })
        used_section_ids.add(consumer_vertical["id"])

    # Основной путь по горизонтальным участкам: от потребителя к щиту
    for edge_idx in reversed(path_edge_indices):
        edge = graph_edges[edge_idx]
        if edge.get("virtual_vertical_link", False):
            continue
        sec_data = {
            "id": edge["id"],
            "length_ft": edge["length_ft"],
            "marker": "трасса"
        }
        path_sections.append(sec_data)
        used_section_ids.add(edge["id"])

    # Включаем ближайший вертикальный участок у щита (если есть)
    panel_vertical = get_nearest_vertical_section_near_point(panel_xy, used_section_ids)
    if panel_vertical is not None:
        path_sections.append({
            "id": panel_vertical["id"],
            "length_ft": panel_vertical["length_ft"],
            "marker": "щит"
        })
        used_section_ids.add(panel_vertical["id"])

    total_path_length_ft = 0.0
    for idx_in_path, sec_data in enumerate(path_sections, 1):
        total_path_length_ft += sec_data["length_ft"]
        marker = sec_data.get("marker", "трасса")
        if marker == "потребитель":
            marker_text = "вертикальный у потребителя"
        elif marker == "щит":
            marker_text = "вертикальный у щита"
        else:
            marker_text = "участок трассы"
        report_lines.append(
            "  {:>2}. ID {:<8} | {:<26} | {:>7.2f} м".format(
                idx_in_path, sec_data["id"], marker_text, ft_to_m(sec_data["length_ft"])
            )
        )
    report_lines.append("Итого по маршруту: {:.2f} м".format(ft_to_m(total_path_length_ft)))
    consumer_reports.append({
        "total_path_length_ft": total_path_length_ft,
        "consumer_name": consumer_name,
        "space_name": space_name,
        "space_number": space_number,
        "level_name": level_name,
        "consumer_name_norm": normalize_text(consumer_name),
        "consumer_id": consumer_id,
        "lines": report_lines
    })


consumer_reports = sorted(
    consumer_reports,
    key=lambda x: (-x["total_path_length_ft"], x["consumer_name_norm"], x["consumer_id"])
)
for report in consumer_reports:
    output_lines.extend(report["lines"])


if not_found_consumers:
    output_lines.append("--------------------------------------------------")
    output_lines.append("Пути не найдены для потребителей: {}".format(len(not_found_consumers)))
    for item in not_found_consumers:
        disconnected_text = "нет"
        if item.get("disconnected_edge_ids"):
            disconnected_text = ", ".join([str(x) for x in item["disconnected_edge_ids"]])
        output_lines.append(
            "  - {} (ID {}) | Пространство: {} ({}) | Уровень: {} | Причина: {} | {} | Участки связной компоненты: {}".format(
                item["name"],
                item["id"],
                item["space_name"],
                item["space_number"],
                item["level_name"],
                item["reason"],
                item.get("nearest_node_debug", "ближайший узел: нет данных"),
                disconnected_text
            )
        )

if not output_lines:
    output_lines = ["Не найдено потребителей разрешенных категорий с построенным путем."]
else:
    output_lines.append("--------------------------------------------------")

# --- ОТЛАДКА: КООРДИНАТЫ ВЕРШИН ГРАФА ---
output_lines.append("Координаты вершин графа (XY, м):")
for idx, node_pt in enumerate(graph_nodes):
    output_lines.append(
        "  - Узел {:>3}: X={:>10.3f} м, Y={:>10.3f} м".format(
            idx,
            ft_to_m(node_pt[0]),
            ft_to_m(node_pt[1])
        )
    )

# --- ОТЛАДКА: КООРДИНАТЫ ПРИВЯЗКИ УЗЛОВ ---
output_lines.append("Координаты привязки узлов (node_match_points, XY, м):")
if node_match_points is None:
    output_lines.append("  - node_match_points не рассчитаны")
else:
    for idx, match_pt in enumerate(node_match_points):
        output_lines.append(
            "  - Узел {:>3}: X={:>10.3f} м, Y={:>10.3f} м".format(
                idx,
                ft_to_m(match_pt[0]),
                ft_to_m(match_pt[1])
            )
        )

# --- ОКНО РЕЗУЛЬТАТА ---
result_window_text = ""
result_can_write = False
result_write_value_m = None
if not not_found_consumers and consumer_reports:
    longest = consumer_reports[0]
    longest_len_m_ceil = ceil_meters(ft_to_m(longest["total_path_length_ft"]))
    consumer_desc = "{}, {} ({}), {}".format(
        longest["consumer_name"],
        longest["space_name"],
        longest["space_number"],
        longest["level_name"]
    )
    result_window_text = (
        "Расчёт трассы максимальной длины в цепи {0} выполнен успешно.\r\n"
        "Максимальная длина - {1}м  до потребителя {2}"
    ).format(circuit_number, longest_len_m_ceil, consumer_desc)
    result_can_write = True
    result_write_value_m = longest_len_m_ceil
else:
    lines = []
    lines.append("Не найден путь к следующим потребителям:")
    if not_found_consumers:
        for item in not_found_consumers:
            lines.append(
                "{0}, {1} ({2}), {3}".format(
                    item["name"],
                    item["space_name"],
                    item["space_number"],
                    item["level_name"]
                )
            )
    else:
        lines.append("нет данных")
    lines.append("")
    lines.append("Проверьте допуски между участками трассы и между потребителями и концами трассы")
    lines.append("Проверьте, что все участки трассы содержат номер цепи {0}".format(circuit_number))
    result_window_text = "\r\n".join(lines)

try:
    if result_can_write:
        show_result_window(
            result_window_text,
            True,
            True,
            revit_automatic,
            result_write_value_m
        )
    else:
        show_result_window(
            result_window_text,
            False,
            False
        )
except:
    pass

OUT = output_lines
