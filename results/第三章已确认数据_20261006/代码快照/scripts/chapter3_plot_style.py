"""Shared typography and drawing parameters for final thesis statistics."""

import hashlib
from pathlib import Path

from matplotlib import font_manager
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.text import Text

INK = "#30363B"
METHOD_COLORS = {"static_astar": "#7B8C96", "safe_serial": "#B58C5B", "coordinated": "#477A9B"}
FAULT_COLORS = {"random": "#477A9B", "path_critical": "#AE7273"}
VERSION_COLORS = {"v1": "#AE7273", "v2": "#477A9B"}
VERSION_LABELS = {"v1": "Before identity check", "v2": "Identity-preserving"}
METHOD_LABELS = {"static_astar": "Uncoordinated A*", "safe_serial": "Safe serial", "coordinated": "Coordinated"}
MARKERS = {"static_astar": "s", "safe_serial": "^", "coordinated": "o"}
LINES = {"static_astar": "--", "safe_serial": ":", "coordinated": "-"}
METHOD_ZORDERS = {"coordinated": 2, "static_astar": 3, "safe_serial": 4}
TITLE_SIZE, LABEL_SIZE, LEGEND_SIZE, TICK_SIZE = 11.5, 10.5, 10.0, 9.5
LINE_WIDTH, MARKER_SIZE, ERROR_WIDTH, CAP_SIZE = 1.35, 4.5, 0.65, 2.0
FIGURE_WIDTH = 6.9


def font_settings():
    try:
        font_manager.findfont(font_manager.FontProperties(family="Arial"), fallback_to_default=False)
        family = "Arial"
    except ValueError:
        family = "DejaVu Sans"
    fonts = {}
    for name, kwargs in (("regular", {}), ("bold", {"weight": "bold"}), ("italic", {"style": "italic"})):
        path = Path(font_manager.findfont(font_manager.FontProperties(family=family, **kwargs)))
        fonts[name] = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    settings = {
        "font.family": family, "font.size": LABEL_SIZE,
        "text.color": INK, "axes.labelcolor": INK, "axes.edgecolor": INK,
        "xtick.color": INK, "ytick.color": INK, "axes.linewidth": 0.65,
        "axes.titleweight": "bold", "axes.titlesize": TITLE_SIZE, "axes.labelsize": LABEL_SIZE,
        "xtick.labelsize": TICK_SIZE, "ytick.labelsize": TICK_SIZE, "legend.fontsize": LEGEND_SIZE,
        "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
        "mathtext.fontset": "custom", "mathtext.rm": family,
        "mathtext.it": family + ":italic", "mathtext.bf": family + ":bold",
        "mathtext.fallback": "stixsans", "pdf.fonttype": 42, "ps.fonttype": 42,
        "pdf.use14corefonts": False, "text.usetex": False,
    }
    return settings, {"family": family, "font_files": fonts}


def panels(rows, cols, height, legend=False, width_ratios=None):
    fig = Figure(figsize=(FIGURE_WIDTH, height), layout="constrained")
    FigureCanvasAgg(fig)
    if not legend:
        return fig, fig.subplots(rows, cols, squeeze=False, width_ratios=width_ratios), None
    grid = fig.add_gridspec(rows + 1, cols, height_ratios=[1] * rows + [0.16], width_ratios=width_ratios)
    axes = [[fig.add_subplot(grid[r, c]) for c in range(cols)] for r in range(rows)]
    legend_ax = fig.add_subplot(grid[-1, :])
    legend_ax.set_axis_off()
    return fig, axes, legend_ax


def decorate(ax, title, ylabel, xlabel=None, grid=True):
    ax.set_title(title, loc="left", pad=7)
    ax.set_ylabel(ylabel, labelpad=5)
    if xlabel:
        ax.set_xlabel(xlabel, labelpad=5)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(direction="out", width=0.6, length=3, pad=3)
    ax.set_axisbelow(True)
    ax.grid(False)
    if grid:
        ax.grid(axis="y", which="major", color="#EBEEF0", linewidth=0.45)
    ax.margins(x=0.06, y=0.12)


def error_line(ax, x, y, errors, color, label, marker="o", linestyle="-", zorder=2, hollow=False):
    container = ax.errorbar(x, y, yerr=errors, color=color, label=label, marker=marker,
        linestyle=linestyle, linewidth=LINE_WIDTH, markersize=MARKER_SIZE,
        markeredgewidth=ERROR_WIDTH, markeredgecolor=color,
        markerfacecolor="none" if hollow else color, elinewidth=ERROR_WIDTH,
        capsize=CAP_SIZE, capthick=ERROR_WIDTH, zorder=zorder)
    for cap in container[1]:
        cap.set_alpha(0.72)
    for collection in container[2]:
        collection.set_alpha(0.65)
    return container


def shared_legend(legend_ax, source_ax, columns):
    handles, labels = source_ax.get_legend_handles_labels()
    legend_ax.legend(handles, labels, loc="center", ncol=columns, frameon=False,
                     handlelength=2.1, handletextpad=0.55, columnspacing=1.3, borderaxespad=0)


def export(fig, output, stem, dpi=300):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    width, height = fig.canvas.get_width_height()
    inactive_tick_labels = set()
    for ax in fig.axes:
        for axis, limits in ((ax.xaxis, ax.get_xlim()), (ax.yaxis, ax.get_ylim())):
            for tick in axis.get_major_ticks() + axis.get_minor_ticks():
                if not min(limits) <= tick.get_loc() <= max(limits):
                    inactive_tick_labels.update((tick.label1, tick.label2))
    # Validate all text, not just axes boxes, before PDF/PNG export.
    for text in fig.findobj(Text):
        if not text.get_visible() or not text.get_text() or text in inactive_tick_labels:
            continue
        bounds = text.get_window_extent(renderer)
        if bounds.x0 < -1 or bounds.y0 < -1 or bounds.x1 > width + 1 or bounds.y1 > height + 1:
            raise ValueError(f"Text would be clipped in {stem}: {text.get_text()}")
    png, pdf = output / "PNG" / (stem + ".png"), output / "PDF" / (stem + ".pdf")
    png.parent.mkdir(parents=True, exist_ok=True)
    pdf.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png, dpi=dpi)
    fig.savefig(pdf)
    return [str(png.resolve()), str(pdf.resolve())]
