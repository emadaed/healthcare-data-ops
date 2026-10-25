rule_id                             rule  true_positives  false_positives  false_negatives  precision   recall       f1
    R01               Duplicate claim_id              12                0                0   1.000000 1.000000 1.000000
    R02           Negative charge amount              17                0                0   1.000000 1.000000 1.000000
    R03             Missing service date              19              314                0   0.057057 1.000000 0.107955
    R04           Invalid procedure code              19              151                0   0.111765 1.000000 0.201058
    R05            Malformed ICD-10 code              19              201                0   0.086364 1.000000 0.158996
    R06                   Orphan payment              14              144                0   0.088608 1.000000 0.162791
    R07                      Overpayment              11                0                3   1.000000 0.785714 0.880000
    R08      Payment before service date               9                0                5   1.000000 0.642857 0.782609
    R09       Paid claim without payment              14              115                0   0.108527 1.000000 0.195804
    R10 Denied claim without denial code              14                0                0   1.000000 1.000000 1.000000
    R11                Duplicate payment              13                0                1   1.000000 0.928571 0.962963
    ALL                        All rules             161              925               21   0.148250 0.884615 0.253943