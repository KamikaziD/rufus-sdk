"""Built-in utilities (rufus object) for JavaScript execution."""

import uuid
from typing import List, Tuple

# JavaScript code defining the rufus utilities object
RUFUS_BUILTINS_JS = """
// Rufus built-in utilities
const rufus = Object.freeze({
    // Logging (captured for audit)
    log: (msg) => __rufus_log__('info', String(msg)),
    warn: (msg) => __rufus_log__('warn', String(msg)),
    error: (msg) => __rufus_log__('error', String(msg)),

    // Date/Time
    now: () => new Date().toISOString(),
    timestamp: () => Date.now(),

    // Identifiers
    uuid: () => __rufus_uuid__(),

    // Math utilities
    sum: (arr) => {
        if (!Array.isArray(arr)) return 0;
        return arr.reduce((a, b) => a + (Number(b) || 0), 0);
    },
    avg: (arr) => {
        if (!Array.isArray(arr) || arr.length === 0) return 0;
        return rufus.sum(arr) / arr.length;
    },
    min: (arr) => Array.isArray(arr) && arr.length > 0 ? Math.min(...arr) : 0,
    max: (arr) => Array.isArray(arr) && arr.length > 0 ? Math.max(...arr) : 0,
    round: (num, decimals = 0) => {
        const factor = Math.pow(10, decimals);
        return Math.round(num * factor) / factor;
    },
    clamp: (num, min, max) => Math.min(Math.max(num, min), max),

    // String utilities
    slugify: (str) => String(str)
        .toLowerCase()
        .trim()
        .replace(/[^\\w\\s-]/g, '')
        .replace(/[\\s_-]+/g, '-')
        .replace(/^-+|-+$/g, ''),
    truncate: (str, len, suffix = '...') => {
        str = String(str);
        return str.length > len ? str.slice(0, len - suffix.length) + suffix : str;
    },
    capitalize: (str) => {
        str = String(str);
        return str.charAt(0).toUpperCase() + str.slice(1).toLowerCase();
    },
    camelCase: (str) => String(str)
        .replace(/[-_\\s]+(.)?/g, (_, c) => c ? c.toUpperCase() : ''),
    snakeCase: (str) => String(str)
        .replace(/([A-Z])/g, '_$1')
        .toLowerCase()
        .replace(/^_/, '')
        .replace(/[-\\s]+/g, '_'),

    // JSON utilities
    parseJSON: (str) => {
        try { return JSON.parse(str); }
        catch { return null; }
    },
    stringify: (obj, pretty = false) => {
        try { return JSON.stringify(obj, null, pretty ? 2 : undefined); }
        catch { return null; }
    },

    // Object utilities
    pick: (obj, keys) => {
        if (!obj || typeof obj !== 'object') return {};
        const result = {};
        for (const key of keys) {
            if (key in obj) result[key] = obj[key];
        }
        return result;
    },
    omit: (obj, keys) => {
        if (!obj || typeof obj !== 'object') return {};
        const result = { ...obj };
        for (const key of keys) delete result[key];
        return result;
    },
    get: (obj, path, defaultValue = undefined) => {
        if (!obj || typeof obj !== 'object') return defaultValue;
        const keys = String(path).split('.');
        let result = obj;
        for (const key of keys) {
            if (result == null || typeof result !== 'object') return defaultValue;
            result = result[key];
        }
        return result === undefined ? defaultValue : result;
    },
    set: (obj, path, value) => {
        if (!obj || typeof obj !== 'object') return obj;
        const keys = String(path).split('.');
        const result = { ...obj };
        let current = result;
        for (let i = 0; i < keys.length - 1; i++) {
            const key = keys[i];
            current[key] = current[key] && typeof current[key] === 'object'
                ? { ...current[key] }
                : {};
            current = current[key];
        }
        current[keys[keys.length - 1]] = value;
        return result;
    },
    merge: (target, ...sources) => {
        const result = { ...target };
        for (const source of sources) {
            if (source && typeof source === 'object') {
                for (const key in source) {
                    result[key] = source[key];
                }
            }
        }
        return result;
    },
    keys: (obj) => obj && typeof obj === 'object' ? Object.keys(obj) : [],
    values: (obj) => obj && typeof obj === 'object' ? Object.values(obj) : [],
    entries: (obj) => obj && typeof obj === 'object' ? Object.entries(obj) : [],

    // Array utilities
    unique: (arr) => Array.isArray(arr) ? [...new Set(arr)] : [],
    flatten: (arr, depth = 1) => Array.isArray(arr) ? arr.flat(depth) : [],
    chunk: (arr, size) => {
        if (!Array.isArray(arr) || size < 1) return [];
        const result = [];
        for (let i = 0; i < arr.length; i += size) {
            result.push(arr.slice(i, i + size));
        }
        return result;
    },
    groupBy: (arr, key) => {
        if (!Array.isArray(arr)) return {};
        return arr.reduce((acc, item) => {
            const group = typeof key === 'function' ? key(item) : item[key];
            (acc[group] = acc[group] || []).push(item);
            return acc;
        }, {});
    },
    sortBy: (arr, key, desc = false) => {
        if (!Array.isArray(arr)) return [];
        return [...arr].sort((a, b) => {
            const aVal = typeof key === 'function' ? key(a) : a[key];
            const bVal = typeof key === 'function' ? key(b) : b[key];
            const cmp = aVal < bVal ? -1 : aVal > bVal ? 1 : 0;
            return desc ? -cmp : cmp;
        });
    },
    first: (arr, n = 1) => {
        if (!Array.isArray(arr)) return n === 1 ? undefined : [];
        return n === 1 ? arr[0] : arr.slice(0, n);
    },
    last: (arr, n = 1) => {
        if (!Array.isArray(arr)) return n === 1 ? undefined : [];
        return n === 1 ? arr[arr.length - 1] : arr.slice(-n);
    },
    compact: (arr) => Array.isArray(arr) ? arr.filter(Boolean) : [],
    zip: (...arrays) => {
        const maxLen = Math.max(...arrays.map(a => Array.isArray(a) ? a.length : 0));
        return Array.from({ length: maxLen }, (_, i) =>
            arrays.map(a => Array.isArray(a) ? a[i] : undefined)
        );
    },

    // Validation utilities
    isEmail: (str) => /^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/.test(String(str)),
    isURL: (str) => {
        try { new URL(String(str)); return true; }
        catch { return false; }
    },
    isUUID: (str) => /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(String(str)),
    isEmpty: (val) => {
        if (val == null) return true;
        if (Array.isArray(val) || typeof val === 'string') return val.length === 0;
        if (typeof val === 'object') return Object.keys(val).length === 0;
        return false;
    },
    isNumber: (val) => typeof val === 'number' && !isNaN(val),
    isString: (val) => typeof val === 'string',
    isArray: (val) => Array.isArray(val),
    isObject: (val) => val !== null && typeof val === 'object' && !Array.isArray(val),
    isBoolean: (val) => typeof val === 'boolean',

    // Type conversion
    toNumber: (val, defaultValue = 0) => {
        const num = Number(val);
        return isNaN(num) ? defaultValue : num;
    },
    toString: (val) => val == null ? '' : String(val),
    toBoolean: (val) => Boolean(val),
    toArray: (val) => {
        if (Array.isArray(val)) return val;
        if (val == null) return [];
        return [val];
    },

    // Date utilities (basic - no external dependencies)
    formatDate: (date, format = 'iso') => {
        const d = date instanceof Date ? date : new Date(date);
        if (isNaN(d.getTime())) return null;
        if (format === 'iso') return d.toISOString();
        if (format === 'date') return d.toISOString().split('T')[0];
        if (format === 'time') return d.toISOString().split('T')[1].split('.')[0];
        return d.toISOString();
    },
    addDays: (date, days) => {
        const d = date instanceof Date ? new Date(date) : new Date(date);
        d.setDate(d.getDate() + days);
        return d.toISOString();
    },
    diffDays: (date1, date2) => {
        const d1 = date1 instanceof Date ? date1 : new Date(date1);
        const d2 = date2 instanceof Date ? date2 : new Date(date2);
        return Math.round((d2 - d1) / (1000 * 60 * 60 * 24));
    }
});
"""


class BuiltinsBridge:
    """Python-side implementation of rufus.* functions that need Python runtime."""

    def __init__(self):
        self.logs: List[Tuple[str, str]] = []

    def log(self, level: str, message: str) -> None:
        """Capture log message."""
        self.logs.append((level, message))

    def uuid(self) -> str:
        """Generate UUID v4."""
        return str(uuid.uuid4())

    def get_logs(self) -> List[Tuple[str, str]]:
        """Return captured logs."""
        return self.logs.copy()

    def clear_logs(self) -> None:
        """Clear captured logs."""
        self.logs.clear()


def get_builtins_js() -> str:
    """Get the JavaScript code defining rufus utilities."""
    return RUFUS_BUILTINS_JS
