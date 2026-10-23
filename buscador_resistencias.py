"""Buscador de combinaciones comerciales de resistencias """

from bisect import bisect_left
import math
import queue
import re
import threading
import tkinter as tk
from tkinter import ttk, messagebox


# Valores preferentes IEC/EIA por década.
E12 = [1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2]
E96 = [
    1.00, 1.02, 1.05, 1.07, 1.10, 1.13, 1.15, 1.18,
    1.21, 1.24, 1.27, 1.30, 1.33, 1.37, 1.40, 1.43,
    1.47, 1.50, 1.54, 1.58, 1.62, 1.65, 1.69, 1.74,
    1.78, 1.82, 1.87, 1.91, 1.96, 2.00, 2.05, 2.10,
    2.15, 2.21, 2.26, 2.32, 2.37, 2.43, 2.49, 2.55,
    2.61, 2.67, 2.74, 2.80, 2.87, 2.94, 3.01, 3.09,
    3.16, 3.24, 3.32, 3.40, 3.48, 3.57, 3.65, 3.74,
    3.83, 3.92, 4.02, 4.12, 4.22, 4.32, 4.42, 4.53,
    4.64, 4.75, 4.87, 4.99, 5.11, 5.23, 5.36, 5.49,
    5.62, 5.76, 5.90, 6.04, 6.19, 6.34, 6.49, 6.65,
    6.81, 6.98, 7.15, 7.32, 7.50, 7.68, 7.87, 8.06,
    8.25, 8.45, 8.66, 8.87, 9.09, 9.31, 9.53, 9.76,
]

# Rango de valores estándar que se evalúa: de 0.1 ohm a varios megaohms.
# Se incluyen ocho décadas: 10^-1, 10^0, ..., 10^6.
DECADES = range(-1, 7)


def build_catalog(tolerance_text):
    """Devuelve (valores, nombre de serie, tolerancia numérica, cifras)."""
    if tolerance_text.startswith("10"):
        base = E12
        series_name = "E12"
        tolerance = 10.0
        significant_digits = 2
    else:
        base = E96
        series_name = "E96"
        tolerance = 1.0
        significant_digits = 3

    values = sorted(round(mantissa * (10.0 ** decade), 8)
                    for decade in DECADES for mantissa in base)
    return values, series_name, tolerance, significant_digits


def parse_resistance(text):
    """Convierte valores como 470, 4.7k, 10 kOhm, 1M o 220 Ω a ohmios."""
    match = re.fullmatch(
        r"\s*([+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([a-zA-ZµμΩω]*)\s*",
        text,
    )
    if not match:
        raise ValueError("Escribe un número positivo, por ejemplo 470, 4.7k o 1M.")

    number = float(match.group(1))
    suffix_raw = match.group(2).strip()
    if not math.isfinite(number) or number <= 0:
        raise ValueError("La resistencia objetivo debe ser un número mayor que cero.")

    # Se permite escribir el símbolo Ω o las palabras ohm/ohms.
    suffix = suffix_raw.replace("Ω", "").replace("ω", "")
    low = suffix.lower()
    if low.endswith("ohms"):
        prefix = suffix[:-4]
    elif low.endswith("ohm"):
        prefix = suffix[:-3]
    else:
        prefix = suffix

    multipliers = {
        "": 1.0,
        "R": 1.0,
        "r": 1.0,
        "k": 1e3,
        "K": 1e3,
        "M": 1e6,
        "m": 1e-3,
        "G": 1e9,
        "g": 1e9,
        "u": 1e-6,
        "µ": 1e-6,
        "μ": 1e-6,
        "meg": 1e6,
        "Meg": 1e6,
        "MEG": 1e6,
        "kilo": 1e3,
        "Kilo": 1e3,
        "mega": 1e6,
        "Mega": 1e6,
        "giga": 1e9,
        "Giga": 1e9,
    }
    if prefix not in multipliers:
        raise ValueError("Unidad no reconocida. Usa Ω, k, M o G; por ejemplo, 4.7k.")

    result = number * multipliers[prefix]
    if not math.isfinite(result) or result <= 0:
        raise ValueError("La resistencia debe ser finita y mayor que cero.")
    return result


def _format_significant(value, significant_digits):
    """Formato con cifras significativas, evitando notación científica común."""
    if value == 0:
        return "0"
    exponent = math.floor(math.log10(abs(value)))
    decimals = max(0, significant_digits - 1 - exponent)
    rendered = f"{value:.{decimals}f}"
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def format_resistance(value, significant_digits=3):
    """Presenta un valor usando Ω, kΩ, MΩ o GΩ."""
    absolute = abs(value)
    if absolute >= 1e9:
        scaled, unit = value / 1e9, "GΩ"
    elif absolute >= 1e6:
        scaled, unit = value / 1e6, "MΩ"
    elif absolute >= 1e3:
        scaled, unit = value / 1e3, "kΩ"
    elif 0 < absolute < 1e-3:
        scaled, unit = value * 1e6, "µΩ"
    else:
        scaled, unit = value, "Ω"
    return f"{_format_significant(scaled, significant_digits)} {unit}"


def neighboring_indices(values, desired_value):
    """Índices comerciales inmediatamente por debajo y encima del valor ideal.

    Como las ecuaciones de cada topología son monótonas respecto a la resistencia
    que se está despejando, esos vecinos bastan para encontrar el valor más próximo
    para cada par fijo de resistencias. Si el valor cae fuera del catálogo se usa
    el extremo disponible.
    """
    if not math.isfinite(desired_value):
        return (len(values) - 1,) if desired_value > 0 else (0,)
    if desired_value <= values[0]:
        return (0,)
    if desired_value >= values[-1]:
        return (len(values) - 1,)
    pos = bisect_left(values, desired_value)
    if values[pos] == desired_value:
        return (pos,)
    return (pos - 1, pos)


def find_best_configurations(target, values, significant_digits=3):
    """Busca la mejor solución total y la mejor de cada topología.

    Tipos evaluados:
      1. Una resistencia.
      2. Dos en serie.
      3. Dos en paralelo.
      4. Tres en serie.
      5. Tres en paralelo.
      6. Dos en serie, conectadas en paralelo con la tercera.
      7. Dos en paralelo, conectadas en serie con la tercera.

    En vez de probar todas las permutaciones triples, se despeja la tercera
    resistencia para cada par posible y se prueban los valores comerciales
    inmediatamente adyacentes. Esto reduce mucho el tiempo de cálculo y conserva
    la mejor aproximación de cada topología.
    """
    best_by_type = {}
    best_overall = None
    series_digits = significant_digits

    def make_config(kind_key, idx_tuple):
        """Construye el texto solo cuando una opción mejora el resultado actual."""
        fmt = lambda index: format_resistance(values[index], series_digits)
        if kind_key == "one":
            return f"R = {fmt(idx_tuple[0])}"
        if kind_key == "two_series":
            a, b = sorted(idx_tuple)
            return f"{fmt(a)} + {fmt(b)}"
        if kind_key == "two_parallel":
            a, b = sorted(idx_tuple)
            return f"{fmt(a)} || {fmt(b)}"
        if kind_key == "three_series":
            return " + ".join(fmt(index) for index in sorted(idx_tuple))
        if kind_key == "three_parallel":
            return " || ".join(fmt(index) for index in sorted(idx_tuple))
        i, j, k = idx_tuple
        if kind_key == "series_pair_parallel_third":
            return f"({fmt(i)} + {fmt(j)}) || {fmt(k)}"
        if kind_key == "parallel_pair_series_third":
            return f"({fmt(i)} || {fmt(j)}) + {fmt(k)}"
        return ""

    def consider(kind_key, kind_label, idx_tuple, components, equivalent):
        nonlocal best_overall
        signed_error = 100.0 * (equivalent - target) / target
        abs_error = abs(signed_error)
        count_components = len(components)
        # Desempate: si dos configuraciones son igual de precisas, se prefiere
        # una que no mezcle resistencias de magnitudes excesivamente distintas.
        spread = max(components) / min(components)
        rank = (abs_error, count_components, spread)
        old_type = best_by_type.get(kind_key)
        improves_type = old_type is None or rank < (
            old_type["abs_error"], old_type["count"], old_type["spread"]
        )
        improves_overall = best_overall is None or rank < (
            best_overall["abs_error"], best_overall["count"], best_overall["spread"]
        )
        if not improves_type and not improves_overall:
            return

        result = {
            "kind_key": kind_key,
            "kind": kind_label,
            "indices": tuple(idx_tuple),
            "components": tuple(components),
            "equivalent": equivalent,
            "signed_error": signed_error,
            "abs_error": abs_error,
            "count": count_components,
            "spread": spread,
            "config": make_config(kind_key, idx_tuple),
        }
        if improves_type:
            best_by_type[kind_key] = result
        if improves_overall:
            best_overall = result

    # Una resistencia: los valores comerciales cercanos al objetivo.
    for idx in neighboring_indices(values, target):
        value = values[idx]
        consider("one", "1 resistencia", (idx,), (value,), value)

    # Dos resistencias: en serie y en paralelo.
    for i, a in enumerate(values):
        # Serie: Req = a + b, por lo que b ideal = objetivo - a.
        desired_b = target - a
        for j in neighboring_indices(values, desired_b):
            b = values[j]
            req = a + b
            ia, ib = sorted((i, j))
            consider("two_series", "2 en serie", (ia, ib), (values[ia], values[ib]), req)

        # Paralelo: 1/Req = 1/a + 1/b.
        if a > target:
            desired_b = (target * a) / (a - target)
        else:
            # Si a <= objetivo, el paralelo siempre queda por debajo del objetivo;
            # una b muy grande hace que Req se aproxime más a a.
            desired_b = values[-1]
        for j in neighboring_indices(values, desired_b):
            b = values[j]
            req = (a * b) / (a + b)
            ia, ib = sorted((i, j))
            consider("two_parallel", "2 en paralelo", (ia, ib), (values[ia], values[ib]), req)

    # Tres resistencias. Se elige un par (a,b) y se despeja el tercer valor c.
    count = len(values)
    for i in range(count):
        a = values[i]
        for j in range(i, count):
            b = values[j]
            pair_sum = a + b
            pair_parallel = (a * b) / (a + b)

            # A) Tres en serie: Req = a + b + c.
            desired_c = target - pair_sum
            for k in neighboring_indices(values, desired_c):
                c = values[k]
                req = pair_sum + c
                indices = tuple(sorted((i, j, k)))
                components = tuple(values[x] for x in indices)
                consider("three_series", "3 en serie", indices, components, req)

            # B) Tres en paralelo: 1/Req = 1/a + 1/b + 1/c.
            remaining_conductance = (1.0 / target) - (1.0 / a) - (1.0 / b)
            if remaining_conductance > 0:
                desired_c = 1.0 / remaining_conductance
            else:
                # El paralelo de a y b ya es <= objetivo: c -> grande es lo mejor.
                desired_c = values[-1]
            for k in neighboring_indices(values, desired_c):
                c = values[k]
                req = 1.0 / ((1.0 / a) + (1.0 / b) + (1.0 / c))
                indices = tuple(sorted((i, j, k)))
                components = tuple(values[x] for x in indices)
                consider("three_parallel", "3 en paralelo", indices, components, req)

            # C) (a + b) || c. La resistencia equivalente aumenta con c.
            if pair_sum > target:
                desired_c = (target * pair_sum) / (pair_sum - target)
            else:
                # El equivalente no puede llegar al objetivo si c es finita;
                # se elige la c máxima para aproximarse desde abajo.
                desired_c = values[-1]
            for k in neighboring_indices(values, desired_c):
                c = values[k]
                req = (pair_sum * c) / (pair_sum + c)
                consider(
                    "series_pair_parallel_third", "(2 serie) en paralelo con 1",
                    (i, j, k), (a, b, c), req,
                )

            # D) (a || b) + c.
            desired_c = target - pair_parallel
            for k in neighboring_indices(values, desired_c):
                c = values[k]
                req = pair_parallel + c
                consider(
                    "parallel_pair_series_third", "(2 paralelo) en serie con 1",
                    (i, j, k), (a, b, c), req,
                )

    # Presentar las siete mejores soluciones por estructura de circuito.
    ordered = sorted(best_by_type.values(), key=lambda x: (x["abs_error"], x["count"], x["spread"]))
    return best_overall, ordered


class ResistorFinderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Buscador de resistencias comerciales")
        self.root.geometry("1120x650")
        self.root.minsize(900, 520)
        self.result_queue = queue.Queue()

        outer = ttk.Frame(root, padding=16)
        outer.pack(fill="both", expand=True)

        ttk.Label(
            outer,
            text="Buscador de resistencias comerciales",
            font=("Segoe UI", 17, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            outer,
            text=(
                "Encuentra la aproximación más cercana usando 1, 2 o 3 resistencias "
                "en conexiones serie/paralelo."
            ),
        ).pack(anchor="w", pady=(3, 14))

        controls = ttk.LabelFrame(outer, text="Parámetros de búsqueda", padding=12)
        controls.pack(fill="x")

        ttk.Label(controls, text="Resistencia deseada:").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=5)
        self.target_var = tk.StringVar(value="1k")
        target_entry = ttk.Entry(controls, textvariable=self.target_var, width=18)
        target_entry.grid(row=0, column=1, sticky="w", pady=5)
        target_entry.bind("<Return>", lambda _event: self.start_search())
        ttk.Label(controls, text="Ejemplos: 470, 4.7k, 1M").grid(row=0, column=2, sticky="w", padx=10)

        ttk.Label(controls, text="Tolerancia comercial:").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=5)
        self.tolerance_var = tk.StringVar(value="10 % (E12)")
        tolerance_box = ttk.Combobox(
            controls,
            textvariable=self.tolerance_var,
            values=("10 % (E12)", "1 % (E96)"),
            state="readonly",
            width=15,
        )
        tolerance_box.grid(row=1, column=1, sticky="w", pady=5)

        self.search_button = ttk.Button(controls, text="Buscar combinaciones", command=self.start_search)
        self.search_button.grid(row=0, column=3, rowspan=2, padx=(20, 4), ipadx=10, ipady=7)

        self.summary_var = tk.StringVar(value="Introduce un valor y pulsa ‘Buscar combinaciones’.")
        ttk.Label(
            outer,
            textvariable=self.summary_var,
            font=("Segoe UI", 10, "bold"),
            wraplength=1060,
        ).pack(anchor="w", pady=(13, 8))

        table_frame = ttk.Frame(outer)
        table_frame.pack(fill="both", expand=True)
        columns = ("type", "equivalent", "error", "configuration")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=12)
        self.tree.heading("type", text="Topología")
        self.tree.heading("equivalent", text="Resistencia equivalente")
        self.tree.heading("error", text="Error respecto al objetivo")
        self.tree.heading("configuration", text="Valores y conexión")
        self.tree.column("type", width=210, minwidth=170, anchor="w")
        self.tree.column("equivalent", width=180, minwidth=150, anchor="center")
        self.tree.column("error", width=190, minwidth=160, anchor="center")
        self.tree.column("configuration", width=480, minwidth=300, anchor="w")
        vertical = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        note = (
            "Nota: 10 % usa valores preferentes E12 y 1 % usa E96. "
            "El error mostrado es la diferencia entre la resistencia equivalente nominal y el objetivo; "
            "no es la tolerancia física acumulada de los componentes. "
            "La búsqueda usa valores de catálogo entre 0.1 Ω y 9.76 MΩ (según la serie)."
        )
        ttk.Label(outer, text=note, wraplength=1060, foreground="#555555").pack(anchor="w", pady=(9, 0))

    def start_search(self):
        try:
            target = parse_resistance(self.target_var.get())
        except ValueError as exc:
            messagebox.showerror("Dato inválido", str(exc), parent=self.root)
            return

        tolerance_text = self.tolerance_var.get()
        values, series_name, tolerance_percent, digits = build_catalog(tolerance_text)
        self.search_button.configure(state="disabled")
        self.summary_var.set("Calculando las mejores combinaciones…")
        for item in self.tree.get_children():
            self.tree.delete(item)

        def worker():
            try:
                overall, by_type = find_best_configurations(target, values, digits)
                self.result_queue.put(("ok", target, series_name, tolerance_percent, digits, overall, by_type))
            except Exception as exc:  # Se comunica cualquier error de cálculo a la interfaz.
                self.result_queue.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(100, self.check_worker_result)

    def check_worker_result(self):
        try:
            item = self.result_queue.get_nowait()
        except queue.Empty:
            self.root.after(100, self.check_worker_result)
            return

        self.search_button.configure(state="normal")
        if item[0] == "error":
            self.summary_var.set("Ocurrió un error durante la búsqueda.")
            messagebox.showerror("Error de cálculo", item[1], parent=self.root)
            return

        _, target, series_name, tolerance_percent, digits, overall, by_type = item
        self.summary_var.set(
            f"Mejor resultado: {format_resistance(overall['equivalent'], 4)}  |  "
            f"Error: {overall['signed_error']:+.5f} %  |  "
            f"{overall['kind']}: {overall['config']}  |  "
            f"Serie {series_name} (±{tolerance_percent:g} %)."
        )
        for result in by_type:
            self.tree.insert(
                "",
                "end",
                values=(
                    result["kind"],
                    format_resistance(result["equivalent"], 4),
                    f"{result['signed_error']:+.5f} %",
                    result["config"],
                ),
            )


def main():
    root = tk.Tk()
    try:
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except tk.TclError:
        pass
    ResistorFinderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
