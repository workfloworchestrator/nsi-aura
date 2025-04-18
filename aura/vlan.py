#  Copyright 2019 SURF.
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

"""VlanRanges object for easy VLAN ranges processing."""

from __future__ import annotations

import operator
from collections import abc
from functools import reduce, total_ordering
from typing import AbstractSet, Any, Iterable, Iterator, List, Optional, Sequence, Tuple, Union, cast

from sqlalchemy import Select, select

from aura.db import Session
from aura.fsm import ConnectionStateMachine
from aura.functional import expand_ranges, to_ranges
from aura.model import STP, Reservation


@total_ordering
class VlanRanges(abc.Set):
    """Represent VLAN ranges.

    This class is quite liberal in what it accepts as valid VLAN ranges. All of:

    - overlapping ranges
    - ranges with start value > stop value
    - ranges with extraneous whitespace

    are all accepted and normalized to a canonical value.

    Examples::

        # These are all equivalent
        VlanRanges("4,10-12,11-14")
        VlanRanges("4,  ,11 - 14, 10-  12")
        VlanRanges("4,10-14")
        VlanRanges([4, 10, 11, 12, 13, 14])
        VlanRanges([[4], [10,12], [11,14]])
        VlanRanges([(4, 4), (10, 14)])

    .. note::

        This class support most :class:`set` operations.
    """

    _vlan_ranges: Tuple[range, ...]

    def __init__(self, val: Optional[Union[str, int, Iterable[int], Sequence[Sequence[int]]]] = None) -> None:
        """Initialize a VlanRange object.

        Args:
            val: something that could be interpreted as one or more VLAN range (see: :class:`VlanRanges`)

        """
        # The idea is to bring all acceptable values to one canonical intermediate format:
        # the `Sequence[Sequence[int]]`.
        # Where the inner sequence is either a one or two element sequence.
        # The one element sequence represents a single VLAN,
        # the two element sequence represents a VLAN range.
        #
        # An example of this intermediate format is::
        #
        #     vlans = [[5], [10, 12]]
        #
        # That example represents 4 VLANs,
        # namely: 5, 10, 11, 12.
        # The latter three VLANs are encode as a range.
        #
        # This intermediate format happens to be the format as accepted by :func:`supa.util.functional.expand_ranges`.
        # This function has the advantage of deduplicating overlapping ranges
        # or VLANs specified more than once.
        # In addition its return value can be used as input to the :func:`supa.util.functional.to_ranges` function.
        vlans: Sequence[Sequence[int]] = []
        if val is None:
            self._vlan_ranges = ()
            return
        if isinstance(val, str):
            if val.strip() != "":
                # This might look complex, but it does handle strings such as `"  3, 4, 6-9, 4, 8 - 10"`
                try:
                    vlans = [list(map(int, s.strip().split("-"))) for s in val.split(",")]
                except ValueError:
                    raise ValueError(f"{val} could not be converted to a {self.__class__.__name__} object.") from None
        elif isinstance(val, int):
            vlans = [[val]]
        elif isinstance(val, abc.Sequence):
            if len(val) > 0:
                if isinstance(val[0], int):
                    vlans = [[x] for x in val]  # type: ignore
                elif isinstance(val[0], abc.Sequence):
                    vlans = cast(Sequence[Sequence[int]], val)
        elif isinstance(val, abc.Iterable):
            vlans = [[x] for x in val]  # type: ignore
        else:
            raise ValueError(f"{val} could not be converted to a {self.__class__.__name__} object.")

        er = expand_ranges(vlans, inclusive=True)
        if er and not (er[0] >= 0 and er[-1] <= 4096):
            raise ValueError(f"{val} is out of range (0-4096).")

        self._vlan_ranges = tuple(to_ranges(er))

    def to_list_of_tuples(self) -> List[Tuple[int, int]]:
        """Construct list of tuples representing the VLAN ranges.

        Example::

            >>> VlanRanges("10 - 12, 8").to_list_of_tuples()
            [(8, 8), (10, 12)]

        Returns:
            The VLAN ranges as contained in this object.

        """
        # `range` objects have an exclusive `stop`.
        # VlanRanges is expressed using terms that use an inclusive stop,
        # which is one less then the exclusive one we use for the internal representation.
        # Hence the `-1`
        return [(vr.start, vr.stop - 1) for vr in self._vlan_ranges]

    def __contains__(self, key: object) -> bool:
        """Membership test."""
        return any(key in range_from_self for range_from_self in self._vlan_ranges)

    def __iter__(self) -> Iterator[int]:
        """Return an iterator that iterates over all the VLANs."""
        # The power of choosing proper abstractions:
        # `range` objects already define an __iter__ method.
        # Hence all wen eed to do,
        # is delegated to them.
        for vr in self._vlan_ranges:
            yield from vr

    def __len__(self) -> int:
        """Return the number of VLANs represented by this VlanRanges object.

        Returns:
            Number of VLAN's

        """
        # Utilize the __iter__ method
        return sum(1 for _ in self)

    def __str__(self) -> str:
        """Create an as compact as possible string representation of VLAN ranges.

        Example::

            >>> str(VlanRanges("1,2,3,4,5-10,8"))
            '1-10'
        """
        # `range` objects have an exclusive `stop`.
        # VlanRanges is expressed using terms that use an inclusive stop,
        # which is one less then the exclusive one we use for the internal representation.
        # Hence the `-1`
        return ",".join(str(vr.start) if len(vr) == 1 else f"{vr.start}-{vr.stop - 1}" for vr in self._vlan_ranges)

    def __repr__(self) -> str:
        """Create string representation of the VLAN ranges that can be used as a valid Python expression.

        Example::

            >>> repr(VlanRanges("1,2,3,4,5-10,8"))
            'VlanRanges([(1, 10)])'

        """
        return f"{self.__class__.__name__}({self.to_list_of_tuples()!s})"

    def __eq__(self, o: object) -> bool:
        """Test for equality."""
        if not isinstance(o, self.__class__):
            return False
        return self._vlan_ranges == o._vlan_ranges

    def __hash__(self) -> int:
        """Calculate hash value."""
        return hash(self._vlan_ranges)

    def __sub__(self, other: Union[int, AbstractSet[Any]]) -> VlanRanges:
        """Remove VLANs from left operand that are in the right operand.

        Examples::

            >>> VlanRanges("1-10") - VlanRanges("5-8")
            VlanRanges([(1, 4), (9, 10)])

        """
        if isinstance(other, int):
            new_set = set(self)
            new_set.remove(other)
            return VlanRanges(new_set)
        return VlanRanges(set(self) - set(other))

    def __and__(self, other: AbstractSet[Any]) -> VlanRanges:
        """Intersection of two VlanRanges objects.

        Example::

            >>> VlanRanges("10-20") & VlanRanges("20-30")
            VlanRanges([(20, 20)])

        """
        return VlanRanges(set(self) & set(other))

    def __or__(self, other: AbstractSet[Any]) -> VlanRanges:
        """Union of two VlanRanges objects.

        Example::

            >>> VlanRanges("10-20") | VlanRanges("20-30")
            VlanRanges([(10, 30)])

        """
        return VlanRanges(set(self) | set(other))

    def __xor__(self, other: AbstractSet[Any]) -> VlanRanges:
        """Symmetric difference of two VlanRanges objects.

        Example::

            >>> VlanRanges("10-20") ^ VlanRanges("20-30")
            VlanRanges([(10, 19), (21, 30)])

        """
        return VlanRanges(set(self) ^ set(other))

    def isdisjoint(self, other: Iterable[Any]) -> bool:
        """Return True if the VlanRanges object has no VLANs in common with the other VlanRanges object."""
        return set(self).isdisjoint(other)

    def union(self, *others: AbstractSet[Any]) -> VlanRanges:
        """Union of two or more VlanRanges objects.

        This does work with sets as well.

        Example::

            >>> VlanRanges("10-20").union(VlanRanges("20-30"), {1,2,3,4})
            VlanRanges([(1, 4), (10, 30)])

        """
        return reduce(operator.__or__, others, self)


def all_vlan_ranges(stpId: int) -> VlanRanges:
    """All VLAN ranges on STP identified by stpId."""
    with Session() as session:
        return VlanRanges(session.query(STP.vlanRange).filter(STP.id == stpId).scalar())  # type: ignore[call-overload]


def _select_in_use_vlan_ranges(select_statement: Select) -> list[int]:
    """Already in use VLAN ranges on STP identified by stpId."""
    with Session() as session:
        return (
            session.execute(select_statement.filter(Reservation.state.in_(ConnectionStateMachine.active_state_values)))  # type: ignore
            .scalars()
            .all()
        )


def in_use_vlan_ranges(stpId: int) -> VlanRanges:
    """Free VLAN ranges on STP identified by stpId."""
    return VlanRanges(
        _select_in_use_vlan_ranges(select(Reservation.sourceVlan).filter(Reservation.sourceStpId == stpId))  # type: ignore
        + _select_in_use_vlan_ranges(select(Reservation.destVlan).filter(Reservation.destStpId == stpId))  # type: ignore
    )


def free_vlan_ranges(stpId: int) -> VlanRanges:
    """Free VLAN ranges on STP identified by stpId."""
    free_vlan_ranges = all_vlan_ranges(stpId)
    for vlan in in_use_vlan_ranges(stpId):
        free_vlan_ranges = free_vlan_ranges - vlan if vlan in free_vlan_ranges else free_vlan_ranges
    return free_vlan_ranges
