#
# Recalibrated Lightweight SKAT
#

from numpy import *
import numpy.linalg
import scipy.linalg

import fastlmm.association.tests

class SKAT_Base(object):
    def process_covariates(self, fixed_covariates=None, add_intercept=True):
        """
        DOCS HERE
        """
        self.X = fixed_covariates

        if add_intercept:
            if self.X is None:
                self.X = ones((self.n, 1))
            else:
                self.X = hstack([self.X, ones((self.n, 1))])
        
        if self.X is not None:
            self.p = shape(self.X)[1]
            assert shape(self.X) == (self.n, self.p)

            # Calculate X+
            self.Xdagger = numpy.linalg.pinv(self.X)

        else:
            self.p = 0

    def compute_scores(self, phenotypes):
        raise NotImplementedError

    def compute_p_value(self, r):
        raise NotImplementedError

    def test(self, phenotypes, return_scores=False, slow=False):
        """
        DOCS HERE
        """

        # Calculate the scores
        scores = self.compute_scores(phenotypes)

        # Calculate the p-values
        pvals = zeros_like(scores)
        for i, r in enumerate(scores):
            pvals[i] = self.compute_p_value(r)

        if return_scores:
            return pvals, scores
        else:
            return pvals

    def _theoretical_variance(self):
        return 2 * (self.n - self.p) / float(self.n - self.p + 2) * (sum(self.phis ** 2) - sum(self.phis)**2 / (self.n - self.p))


class RL_SKAT_Low_Rank(SKAT_Base):
    def __init__(self, weighted_Z=None, fixed_covariates=None, add_intercept=True, zero_threshold=10e-5, phis=None):        
        """
        DOCS HERE
        """
        self.Z = weighted_Z
        self.n, self.m = shape(self.Z)

        self.process_covariates(fixed_covariates=fixed_covariates, add_intercept=add_intercept)

        # Calculate SZ - the  (possibly low rank) square root of SKS        
        if self.X is not None:
            self.SZ = self.Z - numpy.linalg.multi_dot([self.X, self.Xdagger, self.Z])
        else:
            self.SZ = self.Z

        if phis is not None:
            self.phis = phis
        else:
            # Perform the eigendecomposition - phis are square of the SVD of SZ
            self.phis = scipy.linalg.svdvals(self.SZ)**2

            # Pad to length n
            self.phis = concatenate([self.phis, zeros(self.n - len(self.phis))])

            # Round to zero
            self.phis[self.phis < zero_threshold] = 0
            self.phis = sort(self.phis)[::-1]

        # Calculate k = rank(SKS)
        self.k = int(sum(self.phis > 0))

        # Calculate q = dim(ker(SKS) & col(S))
        if self.X is not None:
            B = hstack([self.Z, self.X])
            self.q = int(self.n - sum(scipy.linalg.svdvals(B) > zero_threshold))
        else:
            B = self.Z
            self.q = int(self.n - sum(self.phis > zero_threshold))
        

    
    def compute_scores(self, phenotypes):
        """
        DOCS HERE
        """
        assert shape(phenotypes)[0] == self.n

        if self.X is not None:
            phenotypes_proj = phenotypes - numpy.linalg.multi_dot([self.X, self.Xdagger, phenotypes])
        else:
            phenotypes_proj = phenotypes

        nominators = sum(dot(self.Z.T, phenotypes_proj) ** 2, axis=0)
        denonimators = sum(phenotypes_proj ** 2, axis=0)

        return nominators / denonimators * (self.n - self.p)

    def compute_p_value(self, r):
        alphars = concatenate([self.phis[:self.k] - float(r) / (self.n - self.p), ones(self.q) * -float(r) / (self.n - self.p)])
        return fastlmm.association.tests.Sc.pv_davies_eig(0, alphars)

# The slow formulation
class RL_SKAT_Low_Rank_Chen(RL_SKAT_Low_Rank):
    def compute_p_value(self, r):
        I = identity(self.n)
        if self.X is not None:
            mat = dot(self.SZ, self.SZ.T) - float(r) / (self.n - self.p) * (I - dot(self.X, self.Xdagger))
        else:
            mat = dot(self.SZ, self.SZ.T) - float(r) / (self.n - self.p) * I

        alphars = numpy.linalg.eigvalsh(mat)
        alphars = array(sort(alphars)[::-1])

        return fastlmm.association.tests.Sc.pv_davies_eig(0, alphars)


class SKAT_Inexact_Full_Kernel(SKAT_Base):
    def __init__(self, kernel_matrix=None, fixed_covariates=None, add_intercept=True, zero_threshold=10e-5, phis=None):
        """
        DOCS HERE
        """
        self.K = kernel_matrix
        self.n = len(self.K)
        assert shape(self.K) == (self.n, self.n)

        self.process_covariates(fixed_covariates=fixed_covariates, add_intercept=add_intercept)

        # Calculate SKS - apply S on columns of K and then on rows. S is (I - XX+)  
        if self.X is not None:
            self.SKS = self.K - numpy.linalg.multi_dot([self.X, self.Xdagger, self.K])
            self.SKS -= numpy.linalg.multi_dot([self.SKS, self.Xdagger.T, self.X.T])

        else: 
            self.SKS = self.K

        # Perform the eigendecomposition
        if phis is not None:
            self.phis = phis
        
        else:
            self.phis = numpy.linalg.eigvalsh(self.SKS)

            # Round to zero
            self.phis[self.phis < zero_threshold] = 0
            self.phis = sort(self.phis)[::-1]

        # Calculate k = rank(SKS)
        self.k = int(sum(self.phis > 0))

        # Calculate q = dim(ker(SKS) & col(S))
        if self.X is not None:
            B = hstack([self.K, self.X])
            self.q = int(self.n - sum(scipy.linalg.svdvals(B) > zero_threshold))
        else:
            B = self.K
            self.q = int(self.n - sum(self.phis > zero_threshold))
        

    def compute_scores(self, phenotypes):
        """
        DOCS HERE
        """
        assert shape(phenotypes)[0] == self.n

        nominators = sum(dot(self.SKS, phenotypes) * phenotypes, axis=0)
        if self.X is not None:
            denonimators = sum((phenotypes - numpy.linalg.multi_dot([self.X, self.Xdagger, phenotypes])) * phenotypes, axis=0)
        else:
            denonimators = sum(phenotypes ** 2, axis=0)

        return nominators / denonimators * (self.n - self.p)

    def compute_p_value(self, r):
        # important to drop the very small ones because otherwise it is stuck
        return fastlmm.association.tests.Sc.pv_davies_eig(r, self.phis[where(self.phis > 1e-10)])


class RL_SKAT_Full_Kernel(SKAT_Inexact_Full_Kernel):
    # Override with correction
    def compute_p_value(self, r):
        alphars = concatenate([self.phis[:self.k] - float(r) / (self.n - self.p), ones(self.q) * -float(r) / (self.n - self.p)])
        return fastlmm.association.tests.Sc.pv_davies_eig(0, alphars)


# Exact but  slow formulation
class RL_SKAT_Full_Kernel_Chen(SKAT_Inexact_Full_Kernel):
    def compute_p_value(self, r):
        I = identity(self.n)
        if self.X is not None:
            mat = self.SKS - float(r) / (self.n - self.p) * (I - dot(self.X, self.Xdagger))
        else:
            mat = self.SKS - float(r) / (self.n - self.p) * I

        alphars = numpy.linalg.eigvalsh(mat)
        alphars = array(sort(alphars)[::-1])

        return fastlmm.association.tests.Sc.pv_davies_eig(0, alphars)





# Decide which class to use automatically
class RL_SKAT(object):

    def __init__(self, kernel_matrix=None, random_covariates=None, fixed_covariates=None):
        """
        DOCS HERE
        """
        self.Z = Z = random_covariates
        self.K = K = kernel_matrix
        self.X = X = fixed_covariates

        if (K is None and Z is None) or (K is not None and Z is not None):
            raise "Exactly one of kernel_matrix (K) or random_covariates (Z) must be specified."

        if K is not None:
            n = len(X)
            p = shape(X)[1]

            assert shape(self.kernel_matrix) == (n, n)
            assert shape(self.fixed_covariates)[0] == n