options(stringsAsFactors = FALSE, scipen = 999)

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 5) {
  stop(paste(
    "Usage: Rscript calibrate_opaque_credence.R",
    "<estimate-good> <estimate-bad> <heldout-good> <heldout-bad> <output-dir>"
  ))
}

estimate_good_path <- args[[1]]
estimate_bad_path <- args[[2]]
heldout_good_path <- args[[3]]
heldout_bad_path <- args[[4]]
output_dir <- args[[5]]
dir.create(output_dir, recursive = TRUE, showWarnings = FALSE)

clean_names <- function(x) {
  x <- tolower(x)
  x <- gsub("\\?", "", x)
  x <- gsub("[^a-z0-9]+", "_", x)
  x <- gsub("^_+|_+$", "", x)
  make.unique(x, sep = "_")
}

read_behaviorspace <- function(path) {
  x <- read.csv(path, skip = 6, check.names = FALSE, stringsAsFactors = FALSE)
  names(x) <- clean_names(names(x))
  x
}

write_utf8 <- function(x, name) {
  write.csv(
    x, file.path(output_dir, name), row.names = FALSE,
    na = "", fileEncoding = "UTF-8"
  )
}

assert_calibration_data <- function(x, world, expected_n, label) {
  required <- c(
    "actual_seed", "hidden_world", "ticks", "calibration_expert_q",
    "calibration_message_bin", "expert_total_pulls"
  )
  missing <- setdiff(required, names(x))
  if (length(missing) > 0) {
    stop(sprintf("%s missing columns: %s", label, paste(missing, collapse = ", ")))
  }
  if (nrow(x) != expected_n) stop(sprintf("%s expected %d rows", label, expected_n))
  if (any(x$hidden_world != world)) stop(sprintf("%s contains wrong world", label))
  if (any(x$ticks != 25)) stop(sprintf("%s did not stop at tick 25", label))
  if (any(x$expert_total_pulls != 125)) stop(sprintf("%s expert pull count is not 125", label))
  if (any(x$calibration_expert_q <= 0 | x$calibration_expert_q >= 1)) {
    stop(sprintf("%s contains invalid private credence", label))
  }
  if (any(!(x$calibration_message_bin %in% 0:9))) {
    stop(sprintf("%s contains invalid message bin", label))
  }
  if (any(duplicated(x$actual_seed))) stop(sprintf("%s contains duplicate seeds", label))
  invisible(TRUE)
}

count_bins <- function(x) {
  tabulate(as.integer(x$calibration_message_bin) + 1L, nbins = 10L)
}

wilson_interval <- function(successes, n, z = 1.95996398454005) {
  if (n == 0) return(c(low = NA_real_, high = NA_real_))
  p <- successes / n
  denom <- 1 + z^2 / n
  center <- (p + z^2 / (2 * n)) / denom
  half <- z * sqrt((p * (1 - p) / n) + (z^2 / (4 * n^2))) / denom
  c(low = max(0, center - half), high = min(1, center + half))
}

estimate_good <- read_behaviorspace(estimate_good_path)
estimate_bad <- read_behaviorspace(estimate_bad_path)
heldout_good <- read_behaviorspace(heldout_good_path)
heldout_bad <- read_behaviorspace(heldout_bad_path)

assert_calibration_data(estimate_good, "B-good", 50000, "estimate-good")
assert_calibration_data(estimate_bad, "B-bad", 50000, "estimate-bad")
assert_calibration_data(heldout_good, "B-good", 10000, "heldout-good")
assert_calibration_data(heldout_bad, "B-bad", 10000, "heldout-bad")

all_seed_sets <- list(
  estimate_good = estimate_good$actual_seed,
  estimate_bad = estimate_bad$actual_seed,
  heldout_good = heldout_good$actual_seed,
  heldout_bad = heldout_bad$actual_seed
)
seed_overlap <- 0L
for (i in seq_len(length(all_seed_sets) - 1L)) {
  for (j in (i + 1L):length(all_seed_sets)) {
    seed_overlap <- seed_overlap + length(intersect(all_seed_sets[[i]], all_seed_sets[[j]]))
  }
}

n_good <- count_bins(estimate_good)
n_bad <- count_bins(estimate_bad)
N_good <- sum(n_good)
N_bad <- sum(n_bad)
p_good <- (n_good + 0.5) / (N_good + 5)
p_bad <- (n_bad + 0.5) / (N_bad + 5)
lambda <- log(p_good / p_bad)
lambda_se <- sqrt(
  (1 - p_good) / ((N_good + 5) * p_good) +
    (1 - p_bad) / ((N_bad + 5) * p_bad)
)

parameter_signature <- paste(
  "pA=.50", "pB=.55/.45", "prior=.50", "Thompson",
  "25x5", "deciles", "Jeffreys=.5", sep = "|"
)

frozen <- data.frame(
  table_version = "prehash-v1",
  message_bin = 0:9,
  lower = (0:9) / 10,
  upper = (1:10) / 10,
  midpoint = (0:9) / 10 + 0.05,
  estimate_count_good = n_good,
  estimate_count_bad = n_bad,
  estimate_n_good = N_good,
  estimate_n_bad = N_bad,
  p_message_given_good = p_good,
  p_message_given_bad = p_bad,
  message_lambda = lambda,
  lambda_mc_se = lambda_se,
  implied_p_good_given_message = plogis(lambda),
  estimate_seed_namespace_good = "1000001-1050000",
  estimate_seed_namespace_bad = "1100001-1150000",
  parameter_signature = parameter_signature,
  stringsAsFactors = FALSE
)

held_good_counts <- count_bins(heldout_good)
held_bad_counts <- count_bins(heldout_bad)
held_good_prob <- held_good_counts / sum(held_good_counts)
held_bad_prob <- held_bad_counts / sum(held_bad_counts)

heldout_rows <- lapply(0:9, function(k) {
  total <- held_good_counts[k + 1L] + held_bad_counts[k + 1L]
  empirical <- if (total > 0) held_good_counts[k + 1L] / total else NA_real_
  ci <- wilson_interval(held_good_counts[k + 1L], total)
  data.frame(
    message_bin = k,
    midpoint = k / 10 + 0.05,
    heldout_count_good = held_good_counts[k + 1L],
    heldout_count_bad = held_bad_counts[k + 1L],
    heldout_p_message_given_good = held_good_prob[k + 1L],
    heldout_p_message_given_bad = held_bad_prob[k + 1L],
    frozen_implied_p_good = plogis(lambda[k + 1L]),
    heldout_empirical_p_good = empirical,
    wilson_low = ci[["low"]],
    wilson_high = ci[["high"]],
    absolute_calibration_gap = abs(empirical - plogis(lambda[k + 1L])),
    stringsAsFactors = FALSE
  )
})
heldout_audit <- do.call(rbind, heldout_rows)

tv_good <- 0.5 * sum(abs(held_good_prob - p_good))
tv_bad <- 0.5 * sum(abs(held_bad_prob - p_bad))
max_bin_prob_gap <- max(
  abs(held_good_prob - p_good), abs(held_bad_prob - p_bad)
)
weights <- heldout_audit$heldout_count_good + heldout_audit$heldout_count_bad
weighted_calibration_gap <- weighted.mean(
  heldout_audit$absolute_calibration_gap, weights, na.rm = TRUE
)

checks <- data.frame(
  check = c(
    "estimate_rows_per_world_50000",
    "heldout_rows_per_world_10000",
    "all_expert_runs_have_125_pulls",
    "calibration_seed_namespaces_disjoint",
    "minimum_estimate_cell_count_at_least_200",
    "smoothed_good_probabilities_sum_to_one",
    "smoothed_bad_probabilities_sum_to_one",
    "all_message_lambdas_finite",
    "message_lambda_monotone_in_bin",
    "heldout_total_variation_good_at_most_003",
    "heldout_total_variation_bad_at_most_003",
    "heldout_max_bin_probability_gap_at_most_002",
    "heldout_weighted_calibration_gap_at_most_003"
  ),
  value = c(
    paste(nrow(estimate_good), nrow(estimate_bad), sep = "/"),
    paste(nrow(heldout_good), nrow(heldout_bad), sep = "/"),
    max(abs(c(
      estimate_good$expert_total_pulls, estimate_bad$expert_total_pulls,
      heldout_good$expert_total_pulls, heldout_bad$expert_total_pulls
    ) - 125)),
    seed_overlap,
    min(c(n_good, n_bad)),
    sum(p_good),
    sum(p_bad),
    all(is.finite(lambda)),
    all(diff(lambda) >= 0),
    tv_good,
    tv_bad,
    max_bin_prob_gap,
    weighted_calibration_gap
  ),
  passed = c(
    nrow(estimate_good) == 50000 && nrow(estimate_bad) == 50000,
    nrow(heldout_good) == 10000 && nrow(heldout_bad) == 10000,
    all(c(
      estimate_good$expert_total_pulls, estimate_bad$expert_total_pulls,
      heldout_good$expert_total_pulls, heldout_bad$expert_total_pulls
    ) == 125),
    seed_overlap == 0,
    min(c(n_good, n_bad)) >= 200,
    abs(sum(p_good) - 1) < 1e-12,
    abs(sum(p_bad) - 1) < 1e-12,
    all(is.finite(lambda)),
    all(diff(lambda) >= 0),
    tv_good <= 0.03,
    tv_bad <= 0.03,
    max_bin_prob_gap <= 0.02,
    weighted_calibration_gap <= 0.03
  ),
  stringsAsFactors = FALSE
)

write_utf8(frozen, "frozen_credence_message_table.csv")
write_utf8(heldout_audit, "heldout_calibration_audit.csv")
write_utf8(checks, "calibration_validation_checks.csv")

summary_lines <- c(
  sprintf("Calibration checks passed: %d/%d", sum(checks$passed), nrow(checks)),
  sprintf("Minimum estimation cell count: %d", min(c(n_good, n_bad))),
  sprintf("Held-out TV distance: B-good %.6f; B-bad %.6f", tv_good, tv_bad),
  sprintf("Held-out weighted posterior calibration gap: %.6f", weighted_calibration_gap),
  sprintf("Lambda range: %.6f to %.6f", min(lambda), max(lambda))
)
writeLines(summary_lines, file.path(output_dir, "calibration_key_results.txt"), useBytes = TRUE)

if (!all(checks$passed)) {
  stop("Calibration did not pass all preregistered checks; formal runs must not start")
}

cat(paste(summary_lines, collapse = "\n"), "\n")
