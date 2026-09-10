{% macro safe_divide(numerator, denominator) -%}
    case
        when ({{ denominator }}) = 0 then null
        else ({{ numerator }}) * 1.0 / ({{ denominator }})
    end
{%- endmacro %}
