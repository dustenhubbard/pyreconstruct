class SortStr():

    def __init__(self, s : str):
        self.s = s
    
    def __lt__(self, other):
        s_lower = self.s.lower()
        o_lower = other.s.lower()
        if s_lower == o_lower and self.s < other.s:
            return True
        elif s_lower < o_lower:
            return True
        return False
        
def lessThan(s1, s2):
    """Return True if s1 sorts before s2 in the order sortList uses.

    The lists are built with sortList and updated a row at a time by placing
    names with this, so the two must agree. Comparing numeric names as numbers
    here put "2" before "10" in a list sorted "1", "10", "2": an updated row
    was inserted a second time and a deleted one was never found.
    """
    return SortStr(s1) < SortStr(s2)

def sortList(l):
    ls = [SortStr(s) for s in l]
    ls.sort()
    return [ss.s for ss in ls]