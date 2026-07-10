from __future__ import annotations




GRID_ROWS = 20
GRID_COLS = 20
ELECTRODE_PITCH_MM = 3.2
BOARD_FRAME_MM = 100.0
INITIAL_DROPLET_CAPACITY = 1
RESERVOIR_DROPLET_CAPACITY = 5
MAX_PARALLEL_MULTI_DROPLETS = GRID_ROWS * GRID_COLS
CAMERA_LAYOUT_PADDING_CELLS = 5.4
DROPLET_DETECTION_RGB = (
    (24, 82, 194),
    (178, 58, 72),
    (155, 77, 202),
    (0, 123, 131),
    (199, 125, 0),
    (78, 122, 46),
    (47, 95, 154),
    (125, 79, 42),
)
DROPLET_DETECTION_TOLERANCE = 30

SIDE_RESERVOIR_COLS = (6, 13)
SIDE_RESERVOIR_ROWS = (6, 13)

CORNER_RESERVOIRS = frozenset({(-1, -1), (-1, GRID_COLS), (GRID_ROWS, -1), (GRID_ROWS, GRID_COLS)})
SIDE_RESERVOIR_SMALL = frozenset(
    {(-1, col) for col in SIDE_RESERVOIR_COLS}
    | {(GRID_ROWS, col) for col in SIDE_RESERVOIR_COLS}
    | {(row, -1) for row in SIDE_RESERVOIR_ROWS}
    | {(row, GRID_COLS) for row in SIDE_RESERVOIR_ROWS}
)
SIDE_RESERVOIR_LARGE = frozenset(
    {(-3, col) for col in SIDE_RESERVOIR_COLS}
    | {(GRID_ROWS + 2, col) for col in SIDE_RESERVOIR_COLS}
    | {(row, -3) for row in SIDE_RESERVOIR_ROWS}
    | {(row, GRID_COLS + 2) for row in SIDE_RESERVOIR_ROWS}
)
RESERVOIR_CELLS = frozenset(CORNER_RESERVOIRS | SIDE_RESERVOIR_SMALL | SIDE_RESERVOIR_LARGE)
WASTE_RESERVOIRS = CORNER_RESERVOIRS
DISPENSE_RESERVOIRS = frozenset(RESERVOIR_CELLS - WASTE_RESERVOIRS)
CORE_CELLS = frozenset((row, col) for row in range(GRID_ROWS) for col in range(GRID_COLS))
LAYOUT_CELLS = frozenset(CORE_CELLS | RESERVOIR_CELLS)
RESERVOIR_ID_BY_CELL = {
    (-1, 6): 401,
    (-3, 6): 402,
    (-1, 13): 403,
    (-3, 13): 404,
    (6, GRID_COLS): 405,
    (6, GRID_COLS + 2): 406,
    (13, GRID_COLS): 407,
    (13, GRID_COLS + 2): 408,
    (GRID_ROWS, 13): 409,
    (GRID_ROWS + 2, 13): 410,
    (GRID_ROWS, 6): 411,
    (GRID_ROWS + 2, 6): 412,
    (13, -1): 413,
    (13, -3): 414,
    (6, -1): 415,
    (6, -3): 416,
    (-1, -1): 417,
    (-1, GRID_COLS): 418,
    (GRID_ROWS, GRID_COLS): 419,
    (GRID_ROWS, -1): 420,
}
RESERVOIR_CELL_BY_ID = {eid: cell for cell, eid in RESERVOIR_ID_BY_CELL.items()}

RESERVOIR_CONNECTIONS = {
    (-3, 6): (-1, 6),
    (-3, 13): (-1, 13),
    (-1, 6): (0, 6),
    (-1, 13): (0, 13),
    (GRID_ROWS + 2, 6): (GRID_ROWS, 6),
    (GRID_ROWS + 2, 13): (GRID_ROWS, 13),
    (GRID_ROWS, 6): (GRID_ROWS - 1, 6),
    (GRID_ROWS, 13): (GRID_ROWS - 1, 13),
    (6, -3): (6, -1),
    (13, -3): (13, -1),
    (6, -1): (6, 0),
    (13, -1): (13, 0),
    (6, GRID_COLS + 2): (6, GRID_COLS),
    (13, GRID_COLS + 2): (13, GRID_COLS),
    (6, GRID_COLS): (6, GRID_COLS - 1),
    (13, GRID_COLS): (13, GRID_COLS - 1),
    (-1, -1): (0, 0),
    (-1, GRID_COLS): (0, GRID_COLS - 1),
    (GRID_ROWS, -1): (GRID_ROWS - 1, 0),
    (GRID_ROWS, GRID_COLS): (GRID_ROWS - 1, GRID_COLS - 1),
}

Cell = tuple[int, int]
GridPosition = tuple[float, float]


def electrode_id(row: int, col: int, cols: int = GRID_COLS, rows: int = GRID_ROWS) -> int:
    cell = (row, col)
    if cell in RESERVOIR_ID_BY_CELL:
        return RESERVOIR_ID_BY_CELL[cell]
    if row < 0 or row >= rows or col < 0 or col >= cols:
        raise ValueError(f"Invalid electrode cell ({row}, {col})")
    return row * cols + col + 1


def cell_from_electrode_id(eid: int, cols: int = GRID_COLS, rows: int = GRID_ROWS) -> Cell:
    if eid in RESERVOIR_CELL_BY_ID:
        return RESERVOIR_CELL_BY_ID[eid]
    if eid < 1 or eid > rows * cols:
        raise ValueError(f"Invalid electrode id {eid}")
    idx = eid - 1
    return idx // cols, idx % cols


def cell_center_mm(cell: Cell, pitch_mm: float = ELECTRODE_PITCH_MM) -> tuple[float, float]:
    row, col = cell
    return (col + 0.5) * pitch_mm, (row + 0.5) * pitch_mm


def clamp_cell(cell: Cell, rows: int = GRID_ROWS, cols: int = GRID_COLS) -> Cell:
    row, col = cell
    return max(0, min(rows - 1, row)), max(0, min(cols - 1, col))


def rounded_cell(position: GridPosition, rows: int = GRID_ROWS, cols: int = GRID_COLS) -> Cell:
    candidate = (int(round(position[0])), int(round(position[1])))
    if candidate in LAYOUT_CELLS:
        return candidate
    return clamp_cell(candidate, rows, cols)


def is_reservoir_cell(cell: Cell) -> bool:
    return cell in RESERVOIR_CELLS


def is_waste_reservoir_cell(cell: Cell) -> bool:
    return cell in WASTE_RESERVOIRS


def is_dispense_reservoir_cell(cell: Cell) -> bool:
    return cell in DISPENSE_RESERVOIRS


def is_core_cell(cell: Cell, rows: int = GRID_ROWS, cols: int = GRID_COLS) -> bool:
    row, col = cell
    return 0 <= row < rows and 0 <= col < cols


def are_touching(a: Cell, b: Cell) -> bool:
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) <= 1


def in_pull_risk_zone(a: Cell, b: Cell) -> bool:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1])) <= 1
