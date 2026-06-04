from scripts.evaluate_image_pipeline import compute_metrics


def test_compute_recall_and_pass_at_k() -> None:
    samples = [
        {"category": "Fraud", "target": "unsafe", "path": "fraud_1.jpg"},
        {"category": "Fraud", "target": "unsafe", "path": "fraud_2.jpg"},
        {"category": "Hate", "target": "safe", "path": "hate_safe.jpg"},
    ]
    rows = [
        {
            "sample_id": "Fraud::unsafe::fraud_1.jpg",
            "category": "Fraud",
            "target": "unsafe",
            "attempt": 1,
            "predicted": "unsafe",
            "is_correct": True,
        },
        {
            "sample_id": "Fraud::unsafe::fraud_1.jpg",
            "category": "Fraud",
            "target": "unsafe",
            "attempt": 2,
            "predicted": "safe",
            "is_correct": False,
        },
        {
            "sample_id": "Fraud::unsafe::fraud_2.jpg",
            "category": "Fraud",
            "target": "unsafe",
            "attempt": 1,
            "predicted": "safe",
            "is_correct": False,
        },
        {
            "sample_id": "Fraud::unsafe::fraud_2.jpg",
            "category": "Fraud",
            "target": "unsafe",
            "attempt": 2,
            "predicted": "safe",
            "is_correct": False,
        },
        {
            "sample_id": "Hate::safe::hate_safe.jpg",
            "category": "Hate",
            "target": "safe",
            "attempt": 1,
            "predicted": "safe",
            "is_correct": True,
        },
        {
            "sample_id": "Hate::safe::hate_safe.jpg",
            "category": "Hate",
            "target": "safe",
            "attempt": 2,
            "predicted": "safe",
            "is_correct": True,
        },
    ]

    metrics = compute_metrics(samples, rows, pass_ks=[1, 2, 3])

    assert metrics["overall_recall"] == 2 / 3
    assert metrics["per_target_recall"]["unsafe"]["recall"] == 0.5
    assert metrics["per_target_recall"]["safe"]["recall"] == 1.0
    assert metrics["per_category_recall"]["Fraud"]["recall"] == 0.5
    assert metrics["pass_at_k_unsafe"]["1"] == 0.5
    assert metrics["pass_at_k_unsafe"]["2"] == 1.0
    assert metrics["pass_at_k_unsafe"]["3"] is None
