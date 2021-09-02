import copy
import random

import numpy as np
from scipy.stats import pearsonr
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks

from scripts.common import jc_distance, all_items_equal


class Siscan:
    def __init__(self, align, win_size=200, step_size=20, strip_gaps=True, pvalue_perm_num=1100,
                 scan_perm_num=100, random_seed=3, settings=None):
        """
        Constructs a Siscan object
        :param win_size: the size of the sliding window
        :param step_size: the step size of the sliding window
        :param strip_gaps: Strip gaps or keep gaps
        :param pvalue_perm_num: p-value permutation number
        :param scan_perm_num: number of permutations of the scans
        :param random_seed: the random seed
        """
        self.align = align
        if settings:
            self.set_options_from_config(settings)
            self.validate_options(align)
        else:
            self.win_size = win_size
            self.step_size = step_size
            self.strip_gaps = strip_gaps
            self.pvalue_perm_num = pvalue_perm_num
            self.scan_perm_num = scan_perm_num
            self.random_seed = random_seed

        self.raw_results = []
        self.results = []

    def set_options_from_config(self, settings):
        """
        Set the parameters of Siscan from the  config file
        :param settings: a dictionary of settings
        """
        self.win_size = int(settings['win_size'])
        self.step_size = int(settings['step_size'])

        if settings['strip_gaps'] == 'True':
            self.strip_gaps = True
        else:
            self.strip_gaps = False

        self.pvalue_perm_num = int(settings['pvalue_perm_num'])
        self.scan_perm_num = int(settings['scan_perm_num'])
        self.random_seed = int(settings['random_seed'])

    def validate_options(self, align):
        """
        Check if the options from the config file are valid
        If the options are invalid, the default value will be used instead
        """
        if self.win_size < 0 or self.win_size > align.shape[1]:
            print("Invalid option for 'win_size'.\nUsing default value (200) instead.")
            self.win_size = 200

        if self.step_size < 0 or self.step_size >= self.win_size or self.step_size > align.shape[1]:
            print("Invalid option for 'step_size'.\nUsing default value (20) instead.")
            self.step_size = 20

        if self.pvalue_perm_num <= 0:
            print("Invalid option for 'pvalue_perm_num'.\nUsing default value (1100) instead.")
            self.pvalue_perm_num = 1100

        if self.scan_perm_num <= 0:
            print("Invalid option for 'scan_perm_num'.\nUsing default value (100) instead.")
            self.scan_perm_num = 100

        if self.random_seed <= 0:
            print("Invalid option for 'random_seed'.\nUsing default value (3) instead.")
            self.random_seed = 3

    def count_patterns(self, seq_array):
        a = seq_array[0]
        b = seq_array[1]
        c = seq_array[2]
        d = seq_array[3]

        pat_counts = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]

        ab = a == b
        bc = b == c
        ac = a == c
        ad = a == d
        cd = c == d
        bd = b == d
        np.logical_not(cd)

        pat_counts[0] = np.sum(np.logical_not(ab) & np.logical_not(ac) & np.logical_not(ad) & np.logical_not(bc) & np.logical_not(bd) & np.logical_not(cd))
        pat_counts[1] = np.sum(ab & np.logical_not(ac) & np.logical_not(ad))
        pat_counts[2] = np.sum(ac & np.logical_not(ab) & np.logical_not(ad))
        pat_counts[3] = np.sum(ad & np.logical_not(ab) & np.logical_not(ac))
        pat_counts[4] = np.sum(bc & np.logical_not(ab) & np.logical_not(bd))
        pat_counts[5] = np.sum(bd & np.logical_not(ab) & np.logical_not(bc))
        pat_counts[6] = np.sum(cd & np.logical_not(bc) & np.logical_not(ac))
        pat_counts[7] = np.sum(ab & cd & np.logical_not(bc))
        pat_counts[8] = np.sum(ac & bd & np.logical_not(bc))
        pat_counts[9] = np.sum(ad & bc & np.logical_not(ab))
        pat_counts[10] = np.sum(ab & bc & np.logical_not(ad))
        pat_counts[11] = np.sum(ab & bd & np.logical_not(ac))
        pat_counts[12] = np.sum(ac & cd & np.logical_not(ab))
        pat_counts[13] = np.sum(bc & cd & np.logical_not(ab))
        pat_counts[14] = np.sum(ab & bc & ad)

        return pat_counts

    @staticmethod
    def sum_pattern_counts(pat_counts):
        """
        Sum counts where 2 sequences are identical
        :param pat_counts: vector of counts corresponding to each pattern
        :return: vector of summed counts
        """
        sum_pat_counts = [0, 0, 0, 0, 0, 0, 0, 0, 0]

        sum_pat_counts[3] = pat_counts[1] + pat_counts[7] + pat_counts[10] + pat_counts[11]  # 2 + 8 + 11 + 12
        sum_pat_counts[4] = pat_counts[2] + pat_counts[8] + pat_counts[10] + pat_counts[12]  # 3 + 9 + 11 + 13
        sum_pat_counts[5] = pat_counts[3] + pat_counts[9] + pat_counts[11] + pat_counts[12]  # 4 + 10 + 12 + 13
        sum_pat_counts[6] = pat_counts[4] + pat_counts[9] + pat_counts[10] + pat_counts[13]  # 5 + 10 + 11 + 14
        sum_pat_counts[7] = pat_counts[5] + pat_counts[8] + pat_counts[11] + pat_counts[13]  # 6 + 9 + 12 + 14
        sum_pat_counts[8] = pat_counts[6] + pat_counts[7] + pat_counts[12] + pat_counts[13]  # 7 + 8 + 13 + 14

        return sum_pat_counts

    def execute(self, triplets, quiet=False):
        """
        Do Sister-scanning as described in Gibbs, Armstrong, and Gibbs (2000), using a randomized 4th sequence
        """
        random.seed(self.random_seed)
        np.random.seed(self.random_seed)

        trp_count = 1
        total_num_trps = len(triplets)
        for triplet in triplets:
            if not quiet:
                print("Scanning triplet {} / {}".format(trp_count, total_num_trps))
            trp_count += 1

            # Initialize list to map z_values to window positions
            z_values = np.zeros(triplet.sequences.shape[1])

            # Based on leading edge of the window
            for window in range(0, self.align.shape[1], self.step_size):
                win_start = 0
                win_end = win_start + self.win_size

                # Label sequences
                a = triplet.sequences[0][win_start: win_end]
                b = triplet.sequences[1][win_start: win_end]
                c = triplet.sequences[2][win_start: win_end]

                # Create the fourth sequence through horizontal randomization
                selected_seq = random.choice((0, 1, 2))
                d = triplet.sequences[selected_seq][win_start: win_end]
                np.random.shuffle(d)

                # (1) Count number of positions within a window that conform to each pattern
                seq_array = np.array([a, b, c, d])
                pat_counts = self.count_patterns(seq_array)

                # (2) Sum counts where 2 sequences are identical
                sum_pat_counts = self.sum_pattern_counts(pat_counts)

                # (3) Sum counts of each kind of informative site for each window
                sum_pat_counts[0] = pat_counts[1] + pat_counts[6] + pat_counts[7]  # 2 + 7 + 8
                sum_pat_counts[1] = pat_counts[2] + pat_counts[5] + pat_counts[8]  # 3 + 6 + 9
                sum_pat_counts[2] = pat_counts[3] + pat_counts[4] + pat_counts[9]  # 4 + 5 + 10

                # (4) Create 4 vertically randomized sequences (steps 1 and 2), repeat for 100 times
                p_counts = []
                sum_p_counts = []
                for i in range(self.scan_perm_num):

                    # Generate 4 vertically randomized sequences (shuffle the values in the columns)
                    a1 = seq_array[:, np.random.permutation(seq_array.shape[1])]

                    # Count number of patterns and sum counts
                    p_counts = self.count_patterns(a1)
                    sum_p_counts = self.sum_pattern_counts(p_counts)

                # (5) Calculate Z-scores for each pattern and sum of patterns for each window
                pop_mean_pcounts = np.mean(p_counts)
                pop_mean_patsum = np.mean(sum_p_counts)
                pop_std_pcounts = np.std(p_counts)
                pop_std_patsum = np.std(sum_p_counts)

                pat_zscore = []
                for val in pat_counts:
                    z = (val - pop_mean_pcounts) / pop_std_pcounts
                    pat_zscore.append(z)

                sum_pat_zscore = []
                for val in sum_pat_counts:
                    z = (val - pop_mean_patsum) / pop_std_patsum
                    sum_pat_zscore.append(z)

                # Smooth z-values
                sum_pat_zscore = gaussian_filter1d(sum_pat_zscore, 1.5)

                peaks = find_peaks(sum_pat_zscore, distance=self.win_size)
                for k, peak in enumerate(peaks[0]):
                    search_win_size = 1
                    while peak - search_win_size > 0 \
                            and peak + search_win_size < len(sum_pat_zscore) - 1 \
                            and sum_pat_zscore[peak + search_win_size] > 0.3 * sum_pat_zscore[peak] \
                            and sum_pat_zscore[peak - search_win_size] > 0.3 * sum_pat_zscore[peak]:
                        search_win_size += 1

                    if sum_pat_zscore[peak + search_win_size] > sum_pat_zscore[peak - search_win_size]:
                        aln_pos = (int(peak), int(peak + search_win_size + self.win_size))
                    else:
                        aln_pos = (int(peak - search_win_size), int(peak + self.win_size))

                    rec_name, parents = self.identify_recombinant(triplet, aln_pos)
                    self.raw_results.append((rec_name, parents, *aln_pos, abs(sum_pat_zscore[peak])))

                # self.raw_results.append((triplet, window, pat_zscore, sum_pat_zscore))
                self.raw_results = sorted(self.raw_results)

        self.results = self.merge_breakpoints()
        return self.results

    def identify_recombinant(self, trp, aln_pos):
        """
        Find the most likely recombinant sequence using the PhPr method described in the RDP5 documentation
        and Weiler GF (1998) Phylogenetic profiles: A graphical method for detecting genetic recombinations
        in homologous sequences. Mol Biol Evol 15: 326–335
        :return: name of the recombinant sequence and the names of the parental sequences
        """
        upstream_dists = []
        downstream_dists = []

        # Get possible breakpoint locations
        for i in range(len(trp.names)):
            upstream_dists.append([])
            downstream_dists.append([])
            for j in range(len(trp.names)):
                if i != j:
                    # Calculate pairwise Jukes-Cantor distances for regions upstream and downstream of breakpoint
                    upstream_dists[i].append(jc_distance(trp.sequences[i][0: aln_pos[0]],
                                                         trp.sequences[j][0: aln_pos[0]]))
                    downstream_dists[i].append(jc_distance(trp.sequences[i][aln_pos[1]: trp.sequences.shape[1]],
                                                           trp.sequences[j][aln_pos[1]: trp.sequences.shape[1]]))

        # Calculate Pearson's correlation coefficient for 2 lists
        r_coeff = [0, 0, 0]
        if all_items_equal(upstream_dists[0]) or all_items_equal(downstream_dists[0]):
            r_coeff[0] = float('NaN')
        elif all_items_equal(upstream_dists[1]) or all_items_equal(downstream_dists[1]):
            r_coeff[1] = float('NaN')
        elif all_items_equal(upstream_dists[2]) or all_items_equal(downstream_dists[2]):
            r_coeff[2] = float('NaN')

        else:
            r_coeff[0], _ = pearsonr(upstream_dists[0], downstream_dists[0])
            r_coeff[1], _ = pearsonr(upstream_dists[1], downstream_dists[1])
            r_coeff[2], _ = pearsonr(upstream_dists[2], downstream_dists[2])

        # Most likely recombinant sequence is sequence with lowest coefficient
        trp_names = copy.copy(trp.names)
        rec_name = trp_names.pop(np.argmin(r_coeff))
        p_names = trp_names

        return rec_name, p_names

    def merge_breakpoints(self):
        """
        Merge overlapping breakpoint locations
        :return: list of breakpoint locations where overlapping intervals are merged
        """
        results_dict = {}
        results = []

        # Gather all regions with the same recombinant
        for i, bp in enumerate(self.raw_results):
            rec_name = self.raw_results[i][0]
            parents = tuple(sorted(self.raw_results[i][1]))
            key = (rec_name, parents)
            if key not in results_dict:
                results_dict[key] = []
            results_dict[key].append(self.raw_results[i][2:])

        # Merge any locations that overlap - eg [1, 5] and [3, 7] would become [1, 7]
        for key in results_dict:
            merged_regions = []
            for region in results_dict[key]:
                region = list(region)
                old_regions = list(results_dict[key])
                for region2 in old_regions:
                    start = region[0]
                    end = region[1]
                    start2 = region2[0]
                    end2 = region2[1]
                    if start <= start2 <= end or start <= end2 <= end:
                        region[0] = min(start,start2)
                        region[1] = max(end, end2)
                        results_dict[key].remove(region2)
                merged_regions.append(region)

            # Output the results
            for region in merged_regions:
                rec_name = key[0]
                parents = key[1]
                start = region[0]
                end = region[1]
                p_value = region[2]
                results.append((rec_name, parents, start, end, p_value))

        return results
