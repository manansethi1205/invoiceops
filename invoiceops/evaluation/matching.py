from dataclasses import dataclass

from invoiceops.evaluation.normalization import canonical_value
from invoiceops.evaluation.schemas import GroundTruthLineItem
from invoiceops.schemas.extraction import ExtractionStatus, InvoiceLine

LINE_FIELDS = ("description", "quantity", "unit_price", "line_total")


@dataclass(frozen=True)
class AlignedLineItem:
    ground_truth_index: int
    prediction_index: int
    score: int
    exact: bool


@dataclass(frozen=True)
class _State:
    score: int
    exact_count: int
    pair_count: int
    pairs: tuple[AlignedLineItem, ...]

    @property
    def rank(self) -> tuple[int, int, int]:
        return self.score, self.exact_count, self.pair_count


def predicted_line_value(line: InvoiceLine, field_name: str) -> object | None:
    field = getattr(line, field_name)
    return field.value if field.status == ExtractionStatus.EXTRACTED else None


def line_item_pair_score(truth: GroundTruthLineItem, prediction: InvoiceLine) -> int:
    return sum(
        1
        for field_name in LINE_FIELDS
        if (truth_value := getattr(truth, field_name)) is not None
        and canonical_value(truth_value, field_name)
        == canonical_value(predicted_line_value(prediction, field_name), field_name)
    )


def is_exact_line_item(truth: GroundTruthLineItem, prediction: InvoiceLine) -> bool:
    return all(
        canonical_value(getattr(truth, field_name), field_name)
        == canonical_value(predicted_line_value(prediction, field_name), field_name)
        for field_name in LINE_FIELDS
    )


def align_line_items(
    ground_truth: list[GroundTruthLineItem], predictions: list[InvoiceLine]
) -> list[AlignedLineItem]:
    rows = len(ground_truth)
    columns = len(predictions)
    table = [[_State(0, 0, 0, ()) for _ in range(columns + 1)] for _ in range(rows + 1)]
    for row in range(1, rows + 1):
        for column in range(1, columns + 1):
            candidates = [table[row - 1][column], table[row][column - 1]]
            score = line_item_pair_score(ground_truth[row - 1], predictions[column - 1])
            if score > 0:
                previous = table[row - 1][column - 1]
                exact = is_exact_line_item(ground_truth[row - 1], predictions[column - 1])
                pair = AlignedLineItem(row - 1, column - 1, score, exact)
                candidates.append(
                    _State(
                        previous.score + score,
                        previous.exact_count + int(exact),
                        previous.pair_count + 1,
                        previous.pairs + (pair,),
                    )
                )
            table[row][column] = max(candidates, key=lambda state: state.rank)
    return list(table[rows][columns].pairs)
