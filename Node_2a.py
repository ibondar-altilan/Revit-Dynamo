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

doc = DocumentManager.Instance.CurrentDBDocument


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
]
ALLOWED_CONSUMER_CATEGORIES_NORM = set([normalize_text(x) for x in ALLOWED_CONSUMER_CATEGORIES])


# --- ВХОДЫ ---
if IN is None or len(IN) < 3:
    raise Exception("Ошибка: ожидаются входы IN[0], IN[1], IN[2], IN[3]. Для этапа 1 обязателен IN[2] (автомат).")

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

tolerance_ft = tolerance_m * 3.280839895
# Отдельный допуск для склейки концов участков в узлы графа.
# Делаем его небольшим, чтобы не "съедать" короткие участки возле щита/потребителей.
node_merge_tolerance_ft = min(tolerance_ft, 0.0328084)  # 10 мм в футах


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


def distance_xy(p1, p2):
    dx = p1[0] - p2[0]
    dy = p1[1] - p2[1]
    return math.sqrt(dx * dx + dy * dy)


def ft_to_m(value_ft):
    return value_ft * 0.3048


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
            "p1_xy": (curve.GetEndPoint(1).X, curve.GetEndPoint(1).Y)
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
                "p1_xy": (curve.GetEndPoint(1).X, curve.GetEndPoint(1).Y)
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
                "p1_xy": (pt.X, pt.Y)
            }
            vertical_sections.append(section_data)

if not horizontal_sections:
    raise Exception("Ошибка: в IN[0] не найдено горизонтальных участков трассы.")

# --- ПОСТРОЕНИЕ 2D ГРАФА ТРАССЫ (ТОЛЬКО XY) ---
graph_nodes = []  # [(x, y), ...]
graph_edges = []  # [{"id","element","length_ft","n1","n2"}, ...]
adjacency = {}    # node_index -> [edge_index, ...]


def get_or_create_node_index(pt_xy):
    nearest_idx = None
    nearest_dist = None
    for idx, node_pt in enumerate(graph_nodes):
        d = distance_xy(pt_xy, node_pt)
        if d <= node_merge_tolerance_ft:
            if nearest_dist is None or d < nearest_dist:
                nearest_dist = d
                nearest_idx = idx
    if nearest_idx is not None:
        return nearest_idx
    graph_nodes.append(pt_xy)
    new_idx = len(graph_nodes) - 1
    adjacency[new_idx] = []
    return new_idx


for section in horizontal_sections:
    n1 = get_or_create_node_index(section["p0_xy"])
    n2 = get_or_create_node_index(section["p1_xy"])
    if n1 == n2:
        # Если оба конца попали в один узел из-за допуска, принудительно создаем
        # второй узел для второго конца, чтобы короткий участок не пропал из графа.
        graph_nodes.append(section["p1_xy"])
        n2 = len(graph_nodes) - 1
        adjacency[n2] = []
    edge_data = {
        "id": section["id"],
        "element": section["element"],
        "length_ft": section["length_ft"],
        "n1": n1,
        "n2": n2
    }
    graph_edges.append(edge_data)
    edge_index = len(graph_edges) - 1
    adjacency[n1].append(edge_index)
    adjacency[n2].append(edge_index)


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


# --- ФОРМИРОВАНИЕ ОТЧЕТА ПУТЕЙ К ПОТРЕБИТЕЛЯМ ---
output_lines = []
not_found_consumers = []
consumers_sorted = sorted(
    allowed_consumers,
    key=lambda x: (normalize_text(get_element_display_name(x)), x.Id.IntegerValue)
)

for consumer in consumers_sorted:
    consumer_name = get_element_display_name(consumer)
    consumer_id = consumer.Id.IntegerValue
    space_name = get_param_or_no_data(consumer, "TSL_Имя пространства")
    space_number = get_param_or_no_data(consumer, "TSL_Номер пространства")
    level_name = get_param_or_no_data(consumer, "TSL_Имя уровня")

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

    consumer_node = find_nearest_node_within_tolerance(consumer_xy)
    if consumer_node is None:
        not_found_consumers.append({
            "name": consumer_name,
            "id": consumer_id,
            "space_name": space_name,
            "space_number": space_number,
            "level_name": level_name,
            "reason": "Узел трассы рядом с потребителем не найден в допуске"
        })
        continue

    path_edge_indices = restore_path_edges(consumer_node)
    if not path_edge_indices:
        not_found_consumers.append({
            "name": consumer_name,
            "id": consumer_id,
            "space_name": space_name,
            "space_number": space_number,
            "level_name": level_name,
            "reason": "Путь от щита до потребителя не найден"
        })
        continue

    output_lines.append("--------------------------------------------------")
    output_lines.append("Потребитель: {} (ID {})".format(consumer_name, consumer_id))
    output_lines.append("Маршрут: от потребителя к щиту")
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
        output_lines.append(
            "  {:>2}. ID {:<8} | {:<26} | {:>7.2f} м".format(
                idx_in_path, sec_data["id"], marker_text, ft_to_m(sec_data["length_ft"])
            )
        )
    output_lines.append("Итого по маршруту: {:.2f} м".format(ft_to_m(total_path_length_ft)))


if not_found_consumers:
    output_lines.append("--------------------------------------------------")
    output_lines.append("Пути не найдены для потребителей: {}".format(len(not_found_consumers)))
    for item in not_found_consumers:
        output_lines.append(
            "  - {} (ID {}) | Пространство: {} ({}) | Уровень: {} | Причина: {}".format(
                item["name"], item["id"], item["space_name"], item["space_number"], item["level_name"], item["reason"]
            )
        )

if not output_lines:
    output_lines = ["Не найдено потребителей разрешенных категорий с построенным путем."]
else:
    output_lines.append("--------------------------------------------------")

OUT = output_lines
