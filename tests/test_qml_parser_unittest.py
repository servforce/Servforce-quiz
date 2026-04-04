from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_qml_parser():
    backend_pkg = types.ModuleType("backend")
    backend_pkg.__path__ = [str(ROOT / "backend")]
    sys.modules["backend"] = backend_pkg

    md_quiz_pkg = types.ModuleType("backend.md_quiz")
    md_quiz_pkg.__path__ = [str(ROOT / "backend/md_quiz")]
    sys.modules["backend.md_quiz"] = md_quiz_pkg

    services_pkg = types.ModuleType("backend.md_quiz.services")
    services_pkg.__path__ = [str(ROOT / "backend/md_quiz/services")]
    sys.modules["backend.md_quiz.services"] = services_pkg

    _load_module(
        "backend.md_quiz.services.quiz_metadata",
        ROOT / "backend/md_quiz/services/quiz_metadata.py",
    )
    return _load_module(
        "backend.md_quiz.parsers.qml",
        ROOT / "backend/md_quiz/parsers/qml.py",
    )


class QmlParserRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qml = _load_qml_parser()

    def test_option_text_keeps_dict_literal_after_fenced_code_block(self) -> None:
        exam, public_exam = self.qml.parse_qml_markdown(
            """
## Q31 [single] (1) {answer_time=45s}
在Python3中，下列程序的执行结果为（）

```
dict1 = {'one': 1, 'two': 2, 'three': 3}
dict2 = {'one': 4, 'tmp': 5}
dict1.update(dict2)
print(dict1)
```

* A) {'one': 1, 'two': 2, 'three': 3, 'tmp': 5}
* B) {'one': 4, 'two': 2, 'three': 3}
* C) {'one': 1, 'two': 2, 'three': 3}
* D*) {'one': 4, 'two': 2, 'three': 3, 'tmp': 5}
""".strip()
        )

        self.assertEqual(
            [option["text"] for option in exam["questions"][0]["options"]],
            [
                "{'one': 1, 'two': 2, 'three': 3, 'tmp': 5}",
                "{'one': 4, 'two': 2, 'three': 3}",
                "{'one': 1, 'two': 2, 'three': 3}",
                "{'one': 4, 'two': 2, 'three': 3, 'tmp': 5}",
            ],
        )
        self.assertEqual(
            [option["text"] for option in public_exam["questions"][0]["options"]],
            [
                "{'one': 1, 'two': 2, 'three': 3, 'tmp': 5}",
                "{'one': 4, 'two': 2, 'three': 3}",
                "{'one': 1, 'two': 2, 'three': 3}",
                "{'one': 4, 'two': 2, 'three': 3, 'tmp': 5}",
            ],
        )


if __name__ == "__main__":
    unittest.main()
