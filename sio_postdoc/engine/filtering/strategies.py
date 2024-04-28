"""TODO: Docstring."""

from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import date, datetime, timedelta

import sio_postdoc.utility.service as utility
from sio_postdoc.engine import Dimensions, Units
from sio_postdoc.engine.filtering import Content, Mask
from sio_postdoc.engine.transformation.contracts import (
    DateTime,
    Dimension,
    InstrumentData,
    Values,
    Variable,
)


class AbstractDateStrategy(ABC):
    """TODO: Docstring."""

    @staticmethod
    @abstractmethod
    def apply(target: date, content: Content) -> Content: ...


class NamesByDate(AbstractDateStrategy):
    """TODO: Docstring."""

    @staticmethod
    def apply(target: date, content: Content) -> Content:
        """TODO: Implement."""
        results: list[str] = []
        start: datetime = DateTime(
            year=target.year,
            month=target.month,
            day=target.day,
            hour=0,
            minute=0,
            second=0,
        ).datetime
        end: datetime = start + timedelta(days=1)
        previous_entry: str = ""
        for entry in content:
            current: datetime = utility.extract_datetime(entry).datetime
            if current == start:
                results.append(entry)
            elif start < current < end:
                if not results and previous_entry:
                    results.append(previous_entry)
                results.append(entry)
            elif current == end:
                break
            elif current > end:
                if results:
                    results.append(entry)
                break
            else:
                previous_entry = entry
        return tuple(sorted(results))


class IndicesByDate(AbstractDateStrategy):
    """TODO: Docstring."""

    def apply(
        self, target: date, content: tuple[InstrumentData, ...]
    ) -> InstrumentData:
        """Apply the filtering strategy."""
        # TODO: Too many local variables. You need to break this up.
        # Get the masks
        masks: list[tuple[bool, ...]] = self._get_masks(
            target, content
        )  # TODO: Test this...
        # If the masks are all false, then return None
        if not any(any(m) for m in masks):
            return None
        var_values: dict[str, Values] = defaultdict(list)
        # _get_not_time_indexed_values
        for mask, data in zip(masks, content):
            if not any(mask):
                continue
            for name, var in data.variables.items():
                if not var.dimensions:
                    var_values[name] = var.values
                elif var.dimensions[0].name != Dimensions.TIME:
                    var_values[name] = var.values
            break  # stop going through the masks and data
        # _get_time_indexed_values
        for mask, data in zip(masks, content):
            if not any(mask):
                continue
            for name, var in data.variables.items():
                # You're really just checking the the length is less than 2 and
                if not var.dimensions:
                    continue
                if var.dimensions[0].name != Dimensions.TIME:
                    continue
                if var.units == Units.SECONDS:
                    initial: datetime = datetime.fromtimestamp(
                        data.variables["epoch"].values
                    )
                    var_values[name] += tuple(
                        int(
                            (initial + timedelta(seconds=offset)).timestamp()
                            - var_values["epoch"]
                        )
                        for flag, offset in zip(mask, var.values)
                        if flag
                    )
                    continue
                var_values[name] += list(
                    value for flag, value in zip(mask, var.values) if flag
                )
        # _get_data_dimensions
        data_dims: dict[str, Dimension] = {}
        for required in data.dimensions.keys():
            # This looks a lot like a dictionary
            match required:
                case "time":
                    name = Dimensions.TIME
                    size = len(var_values["offset"])
                case "level":
                    name = Dimensions.LEVEL
                    size = len(var_values["range"])
                case "angle":
                    name = Dimensions.ANGLE
                    size = 4
                case _:
                    continue
            data_dims[required] = Dimension(name=name, size=size)
        # _get_variable_dimensions
        var_dims: dict[str, tuple[Dimension, ...]] = {}
        for key, value in data.variables.items():
            current_dimensions: list[Dimension] = []
            for dimension in value.dimensions:
                match dimension.name:
                    case Dimensions.TIME:
                        name: str = "time"
                    case Dimensions.LEVEL:
                        name: str = "level"
                    case Dimensions.ANGLE:
                        name: str = "angle"
                    case _:
                        continue
                current_dimensions.append(data_dims[name])
            var_dims[key] = tuple(current_dimensions)
        # So, now, how would you create the variables?
        variables: dict[str, Variable] = {
            key: Variable(
                dimensions=var_dims[key],
                dtype=value.dtype,
                long_name=value.long_name,
                scale=value.scale,
                units=value.units,
                values=var_values[key],
            )
            for key, value in data.variables.items()
        }
        new_data: InstrumentData = InstrumentData(
            dimensions=data_dims,
            variables=variables,
        )
        return new_data

    @staticmethod
    def _get_masks(
        target: date, content: tuple[InstrumentData, ...]
    ) -> list[tuple[bool, ...]]:
        masks: list[Mask] = []
        for data in content:
            initial: datetime = datetime.fromtimestamp(data.variables["epoch"].values)
            masks.append(
                tuple(
                    (
                        True
                        if (initial + timedelta(seconds=offset)).date() == target
                        else False
                    )
                    for offset in data.variables["offset"].values
                )
            )
        return masks
